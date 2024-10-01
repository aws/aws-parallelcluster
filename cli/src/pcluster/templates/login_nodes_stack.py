import json
from typing import Dict

from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_logs as logs
from aws_cdk.core import CfnTag, Construct, Fn, NestedStack, Stack, Tags

from pcluster.aws.aws_api import AWSApi
from pcluster.config.cluster_config import LoginNodesPool, SharedStorageType, SlurmClusterConfig
from pcluster.config.common import DefaultUserHomeType
from pcluster.constants import (
    DEFAULT_EPHEMERAL_DIR,
    NODE_BOOTSTRAP_TIMEOUT,
    OS_MAPPING,
    PCLUSTER_LOGIN_NODES_POOL_NAME_TAG,
    PCLUSTER_S3_ARTIFACTS_DICT,
    Feature,
)
from pcluster.templates.cdk_builder_utils import (
    CdkLaunchTemplateBuilder,
    LoginNodesIamResources,
    _get_resource_combination_name,
    create_hash_suffix,
    get_common_user_data_env,
    get_custom_tags,
    get_default_instance_tags,
    get_default_volume_tags,
    get_login_nodes_security_groups_full,
    get_shared_storage_ids_by_type,
    get_source_ingress_rule,
    get_user_data_content,
    to_comma_separated_string,
)
from pcluster.utils import (
    get_attr,
    get_http_tokens_setting,
    get_resource_name_from_resource_arn,
    get_service_endpoint,
    is_feature_supported,
)


class Pool(Construct):
    """Construct defining Login Nodes Pool specific resources."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        pool: LoginNodesPool,
        config: SlurmClusterConfig,
        log_group: logs.CfnLogGroup,
        shared_storage_infos,
        shared_storage_mount_dirs: Dict,
        shared_storage_attributes: Dict,
        login_security_group,
        stack_name,
        stack_id,
        head_eni,
        cluster_bucket,
        cluster_hosted_zone,
    ):
        super().__init__(scope, id)
        self._pool = pool
        self._config = config
        self._log_group = log_group
        self._login_nodes_stack_id = id
        self._shared_storage_infos = shared_storage_infos
        self._shared_storage_mount_dirs = shared_storage_mount_dirs
        self._shared_storage_attributes = shared_storage_attributes
        self._cluster_bucket = cluster_bucket
        self._launch_template_builder = CdkLaunchTemplateBuilder()
        self._login_security_group = login_security_group
        self.stack_name = stack_name
        self.stack_id = stack_id
        self._head_eni = head_eni
        self._cluster_hosted_zone = cluster_hosted_zone
        self._add_resources()

    def _add_resources(self):
        self._add_login_node_iam_resources()
        self._vpc = ec2.Vpc.from_vpc_attributes(
            self,
            f"VPC{self._pool.name}",
            vpc_id=self._config.vpc_id,
            availability_zones=self._pool.networking.az_list,
        )
        self._login_nodes_pool_target_group = self._add_login_nodes_pool_target_group()
        self._load_balancer_security_groups = self._add_load_balancer_security_groups()
        self._login_nodes_pool_load_balancer = self._add_login_nodes_pool_load_balancer(
            self._login_nodes_pool_target_group
        )

        self._launch_template = self._add_login_nodes_pool_launch_template()
        self._add_login_nodes_pool_auto_scaling_group()

        # Add a pool name tag to the pool's resources
        Tags.of(self).add("parallelcluster:login-nodes-pool", self._pool.name)

    def _add_login_node_iam_resources(self):
        self._iam_resource = LoginNodesIamResources(
            self,
            f"LoginNodeIamResources{self._pool.name}",
            self._config,
            self._pool,
            self._shared_storage_infos,
            self._pool.name,
            f"{self._login_nodes_stack_id}-AutoScalingGroup",
        )
        self._instance_profile = self._iam_resource.instance_profile
        self._instance_role = self._iam_resource.instance_role

    def _add_login_nodes_pool_launch_template(self):
        login_nodes_pool_lt_security_groups = get_login_nodes_security_groups_full(
            self._login_security_group,
            self._pool,
        )
        login_nodes_pool_lt_nw_interface = [
            ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                device_index=0,
                interface_type=None,
                groups=login_nodes_pool_lt_security_groups,
                subnet_id=self._pool.networking.subnet_ids[0],
            )
        ]

        ds_config = self._config.directory_service
        ds_generate_keys = str(ds_config.generate_ssh_keys_for_users).lower() if ds_config else "false"

        if self._pool.instance_profile:
            instance_profile_name = get_resource_name_from_resource_arn(self._pool.instance_profile)
            instance_role_name = (
                AWSApi.instance()
                .iam.get_instance_profile(instance_profile_name)
                .get("InstanceProfile")
                .get("Roles")[0]
                .get("RoleName")
            )
        elif self._pool.instance_role:
            instance_role_name = get_resource_name_from_resource_arn(self._pool.instance_role)
        else:
            instance_role_name = self._instance_role.ref

        launch_template_id = f"LoginNodeLaunchTemplate{create_hash_suffix(self._pool.name)}"
        launch_template = ec2.CfnLaunchTemplate(
            Stack.of(self),
            launch_template_id,
            launch_template_name=f"{self.stack_name}-{self._pool.name}",
            launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
                block_device_mappings=self._launch_template_builder.get_block_device_mappings(
                    self._pool.local_storage.root_volume,
                    AWSApi.instance().ec2.describe_image(self._config.login_nodes_ami[self._pool.name]).device_name,
                ),
                image_id=self._config.login_nodes_ami[self._pool.name],
                instance_type=self._pool.instance_type,
                key_name=self._pool.ssh.key_name,
                metadata_options=ec2.CfnLaunchTemplate.MetadataOptionsProperty(
                    http_tokens=get_http_tokens_setting(self._config.imds.imds_support)
                ),
                iam_instance_profile=ec2.CfnLaunchTemplate.IamInstanceProfileProperty(name=self._instance_profile),
                user_data=Fn.base64(
                    Fn.sub(
                        get_user_data_content("../resources/login_node/user_data.sh"),
                        {
                            **{
                                "Timeout": str(
                                    get_attr(
                                        self._config,
                                        "dev_settings.timeouts.compute_node_bootstrap_timeout",
                                        NODE_BOOTSTRAP_TIMEOUT,
                                    )
                                ),
                                "AutoScalingGroupName": f"{self._login_nodes_stack_id}-AutoScalingGroup",
                                "LaunchingLifecycleHookName": (
                                    f"{self._login_nodes_stack_id}-LoginNodesLaunchingLifecycleHook"
                                ),
                                "LaunchTemplateResourceId": launch_template_id,
                                "CloudFormationUrl": get_service_endpoint("cloudformation", self._config.region),
                                "CfnInitRole": instance_role_name,
                            },
                            **get_common_user_data_env(self._pool, self._config),
                        },
                    )
                ),
                network_interfaces=login_nodes_pool_lt_nw_interface,
                tag_specifications=[
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="instance",
                        tags=get_default_instance_tags(
                            self.stack_name, self._config, self._pool, "LoginNode", self._shared_storage_infos
                        )
                        + [CfnTag(key=PCLUSTER_LOGIN_NODES_POOL_NAME_TAG, value=self._pool.name)]
                        + get_custom_tags(self._config),
                    ),
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="volume",
                        tags=get_default_volume_tags(self.stack_name, "LoginNode")
                        + [CfnTag(key=PCLUSTER_LOGIN_NODES_POOL_NAME_TAG, value=self._pool.name)]
                        + get_custom_tags(self._config),
                    ),
                ],
            ),
        )

        dna_json = json.dumps(
            {
                "cluster": {
                    "base_os": self._config.image.os,
                    "cluster_name": self.stack_name,
                    "cluster_user": OS_MAPPING[self._config.image.os]["user"],
                    "cluster_s3_bucket": self._cluster_bucket.name,
                    "cluster_config_s3_key": "{0}/configs/{1}".format(
                        self._cluster_bucket.artifact_directory, PCLUSTER_S3_ARTIFACTS_DICT.get("config_name")
                    ),
                    "cluster_config_version": self._config.config_version,
                    "custom_node_package": self._config.custom_node_package or "",
                    "custom_awsbatchcli_package": self._config.custom_aws_batch_cli_package or "",
                    "cw_logging_enabled": "true" if self._config.is_cw_logging_enabled else "false",
                    "directory_service": {
                        "enabled": str(ds_config is not None).lower(),
                        "domain_read_only_user": ds_config.domain_read_only_user if ds_config else "",
                        "generate_ssh_keys_for_users": ds_generate_keys,
                    },
                    "shared_storage_type": self._config.head_node.shared_storage_type.lower(),
                    "default_user_home": (
                        self._config.deployment_settings.default_user_home.lower()
                        if (
                            self._config.deployment_settings is not None
                            and self._config.deployment_settings.default_user_home is not None
                        )
                        else DefaultUserHomeType.SHARED.value.lower()
                    ),
                    "ebs_shared_dirs": to_comma_separated_string(
                        self._shared_storage_mount_dirs[SharedStorageType.EBS]
                    ),
                    "efs_fs_ids": get_shared_storage_ids_by_type(self._shared_storage_infos, SharedStorageType.EFS),
                    "efs_shared_dirs": to_comma_separated_string(
                        self._shared_storage_mount_dirs[SharedStorageType.EFS]
                    ),
                    "efs_encryption_in_transits": to_comma_separated_string(
                        self._shared_storage_attributes[SharedStorageType.EFS]["EncryptionInTransits"],
                        use_lower_case=True,
                    ),
                    "efs_iam_authorizations": to_comma_separated_string(
                        self._shared_storage_attributes[SharedStorageType.EFS]["IamAuthorizations"],
                        use_lower_case=True,
                    ),
                    "efs_access_point_ids": to_comma_separated_string(
                        self._shared_storage_attributes[SharedStorageType.EFS]["AccessPointIds"],
                        use_lower_case=True,
                    ),
                    "enable_intel_hpc_platform": "true" if self._config.is_intel_hpc_platform_enabled else "false",
                    "ephemeral_dir": DEFAULT_EPHEMERAL_DIR,
                    "fsx_fs_ids": get_shared_storage_ids_by_type(self._shared_storage_infos, SharedStorageType.FSX),
                    "fsx_mount_names": to_comma_separated_string(
                        self._shared_storage_attributes[SharedStorageType.FSX]["MountNames"]
                    ),
                    "fsx_dns_names": to_comma_separated_string(
                        self._shared_storage_attributes[SharedStorageType.FSX]["DNSNames"]
                    ),
                    "fsx_volume_junction_paths": to_comma_separated_string(
                        self._shared_storage_attributes[SharedStorageType.FSX]["VolumeJunctionPaths"]
                    ),
                    "fsx_fs_types": to_comma_separated_string(
                        self._shared_storage_attributes[SharedStorageType.FSX]["FileSystemTypes"]
                    ),
                    "fsx_shared_dirs": to_comma_separated_string(
                        self._shared_storage_mount_dirs[SharedStorageType.FSX]
                    ),
                    "head_node_private_ip": self._head_eni.attr_primary_private_ip_address,
                    "dns_domain": (str(self._cluster_hosted_zone.name) if self._cluster_hosted_zone else ""),
                    "hosted_zone": (str(self._cluster_hosted_zone.ref) if self._cluster_hosted_zone else ""),
                    "dcv_enabled": "login_node" if self._pool.has_dcv_enabled else "false",
                    "dcv_port": self._pool.dcv.port if self._pool.dcv else "NONE",
                    "log_group_name": self._log_group.log_group_name,
                    "log_rotation_enabled": "true" if self._config.is_log_rotation_enabled else "false",
                    "pool_name": self._pool.name,
                    "node_type": "LoginNode",
                    "proxy": self._pool.networking.proxy.http_proxy_address if self._pool.networking.proxy else "NONE",
                    "raid_shared_dir": to_comma_separated_string(
                        self._shared_storage_mount_dirs[SharedStorageType.RAID]
                    ),
                    "raid_type": to_comma_separated_string(
                        self._shared_storage_attributes[SharedStorageType.RAID]["Type"]
                    ),
                    "region": self._config.region,
                    "scheduler": self._config.scheduling.scheduler,
                    "stack_name": self.stack_name,
                    "stack_arn": self.stack_id,
                    "use_private_hostname": str(
                        get_attr(self._config, "scheduling.settings.dns.use_ec2_hostnames", default=False)
                    ).lower(),
                    "disable_sudo_access_for_default_user": (
                        "true"
                        if self._config.deployment_settings
                        and self._config.deployment_settings.disable_sudo_access_default_user
                        else "false"
                    ),
                    "launch_template_id": launch_template_id,
                }
            },
            indent=4,
        )

        cfn_init = {
            "configSets": {
                "deployFiles": ["deployConfigFiles"],
                "update": ["deployConfigFiles", "chefUpdate"],
            },
            "deployConfigFiles": {
                "files": {
                    # A nosec comment is appended to the following line in order to disable the B108 check.
                    # The file is needed by the product
                    # [B108:hardcoded_tmp_directory] Probable insecure usage of temp file/directory.
                    "/tmp/dna.json": {  # nosec B108
                        "content": dna_json,
                        "mode": "000644",
                        "owner": "root",
                        "group": "root",
                        "encoding": "plain",
                    },
                    # A nosec comment is appended to the following line in order to disable the B108 check.
                    # The file is needed by the product
                    # [B108:hardcoded_tmp_directory] Probable insecure usage of temp file/directory.
                    "/tmp/extra.json": {  # nosec B108
                        "mode": "000644",
                        "owner": "root",
                        "group": "root",
                        "content": self._config.extra_chef_attributes,
                    },
                },
                "commands": {
                    "mkdir": {"command": "mkdir -p /etc/chef/ohai/hints"},
                    "touch": {"command": "touch /etc/chef/ohai/hints/ec2.json"},
                    "jq": {
                        "command": (
                            'jq -s ".[0] * .[1]" /tmp/dna.json /tmp/extra.json > /etc/chef/dna.json '
                            '|| ( echo "jq not installed"; cp /tmp/dna.json /etc/chef/dna.json )'
                        )
                    },
                },
            },
            "chefUpdate": {
                "commands": {
                    "chef": {
                        "command": (
                            ". /etc/parallelcluster/pcluster_cookbook_environment.sh; "
                            "cinc-client --local-mode --config /etc/chef/client.rb --log_level info"
                            " --logfile /var/log/chef-client.log --force-formatter --no-color"
                            " --chef-zero-port 8889 --json-attributes /etc/chef/dna.json"
                            " --override-runlist aws-parallelcluster-entrypoints::update &&"
                            " /opt/parallelcluster/scripts/fetch_and_run -postupdate"
                        ),
                        "cwd": "/etc/chef",
                    }
                }
            },
        }

        launch_template.add_metadata("AWS::CloudFormation::Init", cfn_init)

        return launch_template

    def _add_login_nodes_pool_auto_scaling_group(self):
        launch_template_specification = autoscaling.CfnAutoScalingGroup.LaunchTemplateSpecificationProperty(
            launch_template_id=self._launch_template.ref,
            version=self._launch_template.attr_latest_version_number,
        )

        auto_scaling_group = autoscaling.CfnAutoScalingGroup(
            self,
            f"{self._login_nodes_stack_id}-AutoScalingGroup",
            auto_scaling_group_name=f"{self._login_nodes_stack_id}-AutoScalingGroup",
            launch_template=launch_template_specification,
            min_size=str(self._pool.count),
            max_size=str(self._pool.count),
            desired_capacity=str(self._pool.count),
            target_group_arns=[self._login_nodes_pool_target_group.node.default_child.ref],
            vpc_zone_identifier=self._pool.networking.subnet_ids,
            lifecycle_hook_specification_list=[
                self._get_terminating_lifecycle_hook_specification(),
                self._get_launching_lifecycle_hook_specification(),
            ],
        )

        return auto_scaling_group

    def _get_terminating_lifecycle_hook_specification(self):
        return autoscaling.CfnAutoScalingGroup.LifecycleHookSpecificationProperty(
            default_result="ABANDON",
            heartbeat_timeout=self._pool.gracetime_period * 60,
            lifecycle_hook_name=f"{self._login_nodes_stack_id}-LoginNodesTerminatingLifecycleHook",
            lifecycle_transition="autoscaling:EC2_INSTANCE_TERMINATING",
        )

    def _get_launching_lifecycle_hook_specification(self):
        return autoscaling.CfnAutoScalingGroup.LifecycleHookSpecificationProperty(
            default_result="ABANDON",
            heartbeat_timeout=600,
            lifecycle_hook_name=f"{self._login_nodes_stack_id}-LoginNodesLaunchingLifecycleHook",
            lifecycle_transition="autoscaling:EC2_INSTANCE_LAUNCHING",
        )

    def _add_login_nodes_pool_target_group(self):
        return elbv2.NetworkTargetGroup(
            self,
            f"{self._pool.name}TargetGroup",
            health_check=elbv2.HealthCheck(
                port="22",
                protocol=elbv2.Protocol.TCP,
            ),
            port=22,
            protocol=elbv2.Protocol.TCP,
            target_type=elbv2.TargetType.INSTANCE,
            vpc=self._vpc,
            target_group_name=_get_resource_combination_name(
                self._config.cluster_name,
                self._pool.name,
                partial_length=7,
                hash_length=16,
            ),
        )

    def _add_login_nodes_pool_load_balancer(
        self,
        target_group,
    ):
        login_nodes_load_balancer = elbv2.NetworkLoadBalancer(
            self,
            f"{self._pool.name}LoadBalancer",
            vpc=self._vpc,
            internet_facing=self._pool.networking.is_subnet_public,
            vpc_subnets=ec2.SubnetSelection(
                subnets=[
                    ec2.Subnet.from_subnet_id(self, f"LoginNodesSubnet{i}", subnet_id)
                    for i, subnet_id in enumerate(self._pool.networking.subnet_ids)
                ]
            ),
        )
        if is_feature_supported(Feature.NLB_SECURITY_GROUP):
            # This is a workaround to add security groups to the NLB
            # The currently used version of aws-elasticloadbalancingv2 (v1.204) doesn't support
            # creating NLB with security groups directly
            login_nodes_load_balancer.node.default_child.add_property_override(
                "SecurityGroups", self._load_balancer_security_groups
            )
        listener = login_nodes_load_balancer.add_listener(f"LoginNodesListener{self._pool.name}", port=22)
        listener.add_target_groups(f"LoginNodesListenerTargets{self._pool.name}", target_group)
        return login_nodes_load_balancer

    def _add_managed_load_balancer_security_group(self):
        # The load balancer shares the same SSH restrictions as the login nodes
        load_balancer_security_group_ingress = [get_source_ingress_rule(self._pool.ssh.allowed_ips)]

        load_balancer_managed_security_group = ec2.CfnSecurityGroup(
            Stack.of(self),
            f"{self._pool.name}LoadBalancerSecurityGroup",
            group_description=f"Enable access to {self._pool.name} network load balancer",
            vpc_id=self._config.vpc_id,
            security_group_ingress=load_balancer_security_group_ingress,
        )

        # Add a rule to the managed login node security group which grants access from the managed NLB security group
        ec2.CfnSecurityGroupIngress(
            Stack.of(self),
            f"{self._pool.name}LoginSecurityGroupLoadBalancerIngress",
            ip_protocol="-1",
            from_port=0,
            to_port=65535,
            source_security_group_id=load_balancer_managed_security_group.ref,
            description=f"Allow traffic from {self._pool.name} network load balancer",
            group_id=self._login_security_group.ref,
        )

        return load_balancer_managed_security_group

    def _add_load_balancer_security_groups(self):
        """Return all of the security groups to be used on the Network Load Balancer."""
        managed_load_balancer_security_group = None
        if not self._pool.networking.security_groups:
            managed_load_balancer_security_group = self._add_managed_load_balancer_security_group()
            # Get the same security groups used on the login node pool
        load_balancer_security_groups = get_login_nodes_security_groups_full(
            managed_load_balancer_security_group, self._pool
        )
        return load_balancer_security_groups


class LoginNodesStack(NestedStack):
    """Stack encapsulating a set of LoginNodes and the associated resources."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        cluster_config: SlurmClusterConfig,
        log_group: logs.CfnLogGroup,
        shared_storage_infos: Dict,
        shared_storage_mount_dirs: Dict,
        shared_storage_attributes: Dict,
        login_security_groups,
        head_eni,
        cluster_hosted_zone,
        cluster_bucket,
    ):
        super().__init__(scope, id)
        self._login_nodes = cluster_config.login_nodes
        self._config = cluster_config
        self._log_group = log_group
        self._login_security_groups = login_security_groups
        self._shared_storage_infos = shared_storage_infos
        self._shared_storage_mount_dirs = shared_storage_mount_dirs
        self._shared_storage_attributes = shared_storage_attributes
        self._head_eni = head_eni
        self._cluster_hosted_zone = cluster_hosted_zone
        self._cluster_bucket = cluster_bucket
        self._add_resources()

    @property
    def stack_name(self):
        """Name of the CFN stack."""
        return Stack.of(self.nested_stack_parent).stack_name

    def _add_resources(self):
        self.pools = {}
        for pool in self._login_nodes.pools:
            pool_construct = Pool(
                self,
                f"{self._config.cluster_name}-{pool.name}",
                pool,
                self._config,
                self._log_group,
                self._shared_storage_infos,
                self._shared_storage_mount_dirs,
                self._shared_storage_attributes,
                self._login_security_groups.get(pool.name),
                self.stack_name,
                self.stack_id,
                self._head_eni,
                self._cluster_bucket,
                cluster_hosted_zone=self._cluster_hosted_zone,
            )
            self.pools[pool.name] = pool_construct
