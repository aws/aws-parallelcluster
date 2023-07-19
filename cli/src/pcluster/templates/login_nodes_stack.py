from typing import Dict

from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_logs as logs
from aws_cdk.core import CfnTag, Construct, Fn, NestedStack, Stack

from pcluster.config.cluster_config import LoginNodesPool, SharedStorageType, SlurmClusterConfig
from pcluster.constants import (
    DEFAULT_EPHEMERAL_DIR,
    NODE_BOOTSTRAP_TIMEOUT,
    OS_MAPPING,
    PCLUSTER_LOGIN_NODES_POOL_NAME_TAG,
)
from pcluster.templates.cdk_builder_utils import (
    CdkLaunchTemplateBuilder,
    LoginNodesIamResources,
    get_common_user_data_env,
    get_default_instance_tags,
    get_default_volume_tags,
    get_login_nodes_security_groups_full,
    get_shared_storage_ids_by_type,
    get_user_data_content,
    to_comma_separated_string,
)
from pcluster.utils import get_attr, get_http_tokens_setting


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
        head_eni,
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
        self._login_security_group = login_security_group
        self.stack_name = stack_name
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
        self._login_nodes_pool_load_balancer = self._add_login_nodes_pool_load_balancer(
            self._login_nodes_pool_target_group
        )

        self._launch_template = self._add_login_nodes_pool_launch_template()
        self._add_login_nodes_pool_auto_scaling_group()

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
        return ec2.CfnLaunchTemplate(
            self,
            f"LoginNodeLaunchTemplate{self._pool.name}",
            launch_template_name=f"{self.stack_name}-{self._pool.name}",
            launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
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
                                "BaseOS": self._config.image.os,
                                "ClusterName": self.stack_name,
                                "ClusterDNSDomain": str(self._cluster_hosted_zone.name)
                                if self._cluster_hosted_zone
                                else "",
                                "ClusterHostedZone": str(self._cluster_hosted_zone.ref)
                                if self._cluster_hosted_zone
                                else "",
                                "CustomNodePackage": self._config.custom_node_package or "",
                                "CustomAwsBatchCliPackage": self._config.custom_aws_batch_cli_package or "",
                                "CWLoggingEnabled": "true" if self._config.is_cw_logging_enabled else "false",
                                "DirectoryServiceEnabled": str(ds_config is not None).lower(),
                                "DirectoryServiceReadOnlyUser": ds_config.domain_read_only_user if ds_config else "",
                                "DirectoryServiceGenerateSshKeys": ds_generate_keys,
                                "EbsSharedDirs": to_comma_separated_string(
                                    self._shared_storage_mount_dirs[SharedStorageType.EBS]
                                ),
                                "EFSIds": get_shared_storage_ids_by_type(
                                    self._shared_storage_infos, SharedStorageType.EFS
                                ),
                                "EFSSharedDirs": to_comma_separated_string(
                                    self._shared_storage_mount_dirs[SharedStorageType.EFS]
                                ),
                                "EFSEncryptionInTransits": to_comma_separated_string(
                                    self._shared_storage_attributes[SharedStorageType.EFS]["EncryptionInTransits"],
                                    use_lower_case=True,
                                ),
                                "EFSIamAuthorizations": to_comma_separated_string(
                                    self._shared_storage_attributes[SharedStorageType.EFS]["IamAuthorizations"],
                                    use_lower_case=True,
                                ),
                                "EphemeralDir": DEFAULT_EPHEMERAL_DIR,
                                "ExtraJson": self._config.extra_chef_attributes,
                                "FSXIds": get_shared_storage_ids_by_type(
                                    self._shared_storage_infos, SharedStorageType.FSX
                                ),
                                "FSXMountNames": to_comma_separated_string(
                                    self._shared_storage_attributes[SharedStorageType.FSX]["MountNames"]
                                ),
                                "FSXDNSNames": to_comma_separated_string(
                                    self._shared_storage_attributes[SharedStorageType.FSX]["DNSNames"]
                                ),
                                "FSXVolumeJunctionPaths": to_comma_separated_string(
                                    self._shared_storage_attributes[SharedStorageType.FSX]["VolumeJunctionPaths"]
                                ),
                                "FSXFileSystemTypes": to_comma_separated_string(
                                    self._shared_storage_attributes[SharedStorageType.FSX]["FileSystemTypes"]
                                ),
                                "FSXSharedDirs": to_comma_separated_string(
                                    self._shared_storage_mount_dirs[SharedStorageType.FSX]
                                ),
                                "HeadNodePrivateIp": self._head_eni.attr_primary_private_ip_address,
                                "IntelHPCPlatform": "true" if self._config.is_intel_hpc_platform_enabled else "false",
                                "LogGroupName": self._log_group.log_group_name,
                                "LogRotationEnabled": "true" if self._config.is_log_rotation_enabled else "false",
                                "OSUser": OS_MAPPING[self._config.image.os]["user"],
                                "RAIDSharedDir": to_comma_separated_string(
                                    self._shared_storage_mount_dirs[SharedStorageType.RAID]
                                ),
                                "RAIDType": to_comma_separated_string(
                                    self._shared_storage_attributes[SharedStorageType.RAID]["Type"]
                                ),
                                "Scheduler": self._config.scheduling.scheduler,
                                "UsePrivateHostname": str(
                                    get_attr(self._config, "scheduling.settings.dns.use_ec2_hostnames", default=False)
                                ).lower(),
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
                        + [CfnTag(key=PCLUSTER_LOGIN_NODES_POOL_NAME_TAG, value=self._pool.name)],
                    ),
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="volume",
                        tags=get_default_volume_tags(self.stack_name, "LoginNode")
                        + [CfnTag(key=PCLUSTER_LOGIN_NODES_POOL_NAME_TAG, value=self._pool.name)],
                    ),
                ],
            ),
        )

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
        )
        self.terminating_lifecycle_hook = self._add_terminating_lifecycle_hook(auto_scaling_group)
        self.launching_lifecycle_hook = self._add_launching_lifecycle_hook(auto_scaling_group)

        return auto_scaling_group

    def _add_terminating_lifecycle_hook(self, auto_scaling_group):
        return autoscaling.CfnLifecycleHook(
            self,
            "LoginNodesASGLifecycleHookTerminating",
            auto_scaling_group_name=auto_scaling_group.ref,
            lifecycle_transition="autoscaling:EC2_INSTANCE_TERMINATING",
            lifecycle_hook_name=f"{self._login_nodes_stack_id}-LoginNodesTerminatingLifecycleHook",
            heartbeat_timeout=self._pool.gracetime_period * 60,
        )

    def _add_launching_lifecycle_hook(self, auto_scaling_group):
        return autoscaling.CfnLifecycleHook(
            self,
            "LoginNodesASGLifecycleHookLaunching",
            auto_scaling_group_name=auto_scaling_group.ref,
            lifecycle_hook_name=f"{self._login_nodes_stack_id}-LoginNodesLaunchingLifecycleHook",
            lifecycle_transition="autoscaling:EC2_INSTANCE_LAUNCHING",
            default_result="ABANDON",
            heartbeat_timeout=600,
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

        listener = login_nodes_load_balancer.add_listener(f"LoginNodesListener{self._pool.name}", port=22)
        listener.add_target_groups(f"LoginNodesListenerTargets{self._pool.name}", target_group)
        return login_nodes_load_balancer


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
        login_security_group,
        head_eni,
        cluster_hosted_zone,
    ):
        super().__init__(scope, id)
        self._login_nodes = cluster_config.login_nodes
        self._config = cluster_config
        self._log_group = log_group
        self._login_security_group = login_security_group
        self._launch_template_builder = CdkLaunchTemplateBuilder()
        self._shared_storage_infos = shared_storage_infos
        self._shared_storage_mount_dirs = shared_storage_mount_dirs
        self._shared_storage_attributes = shared_storage_attributes
        self._head_eni = head_eni
        self._cluster_hosted_zone = cluster_hosted_zone
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
                self._login_security_group,
                self.stack_name,
                self._head_eni,
                cluster_hosted_zone=self._cluster_hosted_zone,
            )
            self.pools[pool.name] = pool_construct
