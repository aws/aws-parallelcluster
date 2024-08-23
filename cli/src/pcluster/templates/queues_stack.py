import json
from typing import Dict, List

from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_logs as logs
from aws_cdk.core import CfnTag, Fn, NestedStack, Stack
from constructs import Construct

from pcluster.aws.aws_api import AWSApi
from pcluster.config.cluster_config import SharedStorageType, SlurmClusterConfig, SlurmComputeResource, SlurmQueue
from pcluster.config.common import DefaultUserHomeType
from pcluster.constants import (
    DEFAULT_EPHEMERAL_DIR,
    NODE_BOOTSTRAP_TIMEOUT,
    OS_MAPPING,
    PCLUSTER_COMPUTE_RESOURCE_NAME_TAG,
    PCLUSTER_QUEUE_NAME_TAG,
    PCLUSTER_S3_ARTIFACTS_DICT,
)
from pcluster.models.s3_bucket import S3FileFormat, S3FileType
from pcluster.templates.cdk_builder_utils import (
    CdkLaunchTemplateBuilder,
    ComputeNodeIamResources,
    create_hash_suffix,
    dict_to_cfn_tags,
    get_common_user_data_env,
    get_custom_tags,
    get_default_instance_tags,
    get_default_volume_tags,
    get_queue_security_groups_full,
    get_shared_storage_ids_by_type,
    get_user_data_content,
    scheduler_is_slurm,
    to_comma_separated_string,
)
from pcluster.templates.slurm_builder import SlurmConstruct
from pcluster.utils import get_attr, get_http_tokens_setting, get_resource_name_from_resource_arn, get_service_endpoint


class QueuesStack(NestedStack):
    """Stack encapsulating a set of queues and the associated resources."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        queues: List[SlurmQueue],
        slurm_construct: SlurmConstruct,
        cluster_config: SlurmClusterConfig,
        log_group: logs.CfnLogGroup,
        shared_storage_infos: Dict,
        shared_storage_mount_dirs: Dict,
        shared_storage_attributes: Dict,
        compute_security_group,
        cluster_hosted_zone,
        dynamodb_table,
        head_eni,
        cluster_bucket,
    ):
        super().__init__(scope, id)
        self._queues = queues
        self._slurm_construct = slurm_construct
        self._config = cluster_config
        self._shared_storage_infos = shared_storage_infos
        self._shared_storage_mount_dirs = shared_storage_mount_dirs
        self._shared_storage_attributes = shared_storage_attributes
        self._compute_security_group = compute_security_group
        self._log_group = log_group
        self._cluster_hosted_zone = cluster_hosted_zone
        self._dynamodb_table = dynamodb_table
        self._head_eni = head_eni
        self._cluster_bucket = cluster_bucket
        self._launch_template_builder = CdkLaunchTemplateBuilder()
        self._add_resources()

    @staticmethod
    def _get_placement_group_for_compute_resource(queue, managed_placement_groups, compute_resource) -> str:
        placement_group_settings = queue.get_placement_group_settings_for_compute_resource(compute_resource)
        placement_group_key = placement_group_settings.get("key")
        managed = placement_group_settings.get("is_managed")
        return managed_placement_groups[placement_group_key].ref if managed else placement_group_key

    @property
    def stack_name(self):
        """Name of the CFN stack."""
        return Stack.of(self.nested_stack_parent).stack_name

    def _add_resources(self):
        self._add_compute_iam_resources()
        self._add_placement_groups()
        self._add_launch_templates()

    def _add_placement_groups(self):
        self.managed_placement_groups = {}
        for queue in self._queues:
            for key in queue.get_managed_placement_group_keys():
                self.managed_placement_groups[key] = ec2.CfnPlacementGroup(
                    self,
                    f"PlacementGroup{create_hash_suffix(key)}",
                    strategy="cluster",
                )

    def _add_compute_iam_resources(self):
        iam_resources = {}
        for queue in self._queues:
            iam_resources[queue.name] = ComputeNodeIamResources(
                self,
                f"ComputeNodeIamResources{queue.name}",
                self._config,
                queue,
                self._shared_storage_infos,
                queue.name,
                self._cluster_bucket,
            )
        self._compute_instance_profiles = {k: v.instance_profile for k, v in iam_resources.items()}
        self.managed_compute_instance_roles = {k: v.instance_role for k, v in iam_resources.items()}
        if scheduler_is_slurm(self._config):
            self._slurm_construct.register_policies_with_role(
                scope=Stack.of(self),
                managed_compute_instance_roles=self.managed_compute_instance_roles,
            )

    def _add_launch_templates(self):
        self.compute_launch_templates = {}
        for queue in self._queues:
            self.compute_launch_templates[queue.name] = {}
            queue_lt_security_groups = get_queue_security_groups_full(self._compute_security_group, queue)

            for resource in queue.compute_resources:
                self.compute_launch_templates[queue.name][resource.name] = self._add_compute_resource_launch_template(
                    queue,
                    resource,
                    queue_lt_security_groups,
                    self._get_placement_group_for_compute_resource(queue, self.managed_placement_groups, resource),
                    self._compute_instance_profiles,
                    self._config.is_detailed_monitoring_enabled,
                )

    def _get_custom_compute_resource_tags(self, queue_config, compute_resource_config):
        """Compute resource tags and Queue Tags value on Cluster level tags if there are duplicated keys."""
        tags = get_custom_tags(self._config, raw_dict=True)
        queue_tags = get_custom_tags(queue_config, raw_dict=True)
        compute_resource_tags = get_custom_tags(compute_resource_config, raw_dict=True)
        return dict_to_cfn_tags({**tags, **queue_tags, **compute_resource_tags})

    def _add_compute_resource_launch_template(
        self,
        queue,
        compute_resource,
        queue_lt_security_groups,
        placement_group,
        instance_profiles,
        is_detailed_monitoring_enabled,
    ):
        # LT network interfaces
        compute_lt_nw_interfaces = [
            ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                device_index=0,
                network_card_index=0,
                associate_public_ip_address=queue.networking.assign_public_ip,
                interface_type="efa" if compute_resource.efa and compute_resource.efa.enabled else None,
                groups=queue_lt_security_groups,
                subnet_id=(
                    queue.networking.subnet_ids[0] if isinstance(compute_resource, SlurmComputeResource) else None
                ),
            )
        ]

        for network_card in compute_resource.network_cards_list[1:]:
            compute_lt_nw_interfaces.append(
                ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                    device_index=0 if network_card.maximum_network_interfaces() == 1 else 1,
                    network_card_index=network_card.network_card_index(),
                    associate_public_ip_address=False,
                    interface_type="efa" if compute_resource.efa and compute_resource.efa.enabled else None,
                    groups=queue_lt_security_groups,
                    subnet_id=(
                        queue.networking.subnet_ids[0] if isinstance(compute_resource, SlurmComputeResource) else None
                    ),
                )
            )

        conditional_template_properties = {}
        if compute_resource.is_ebs_optimized:
            conditional_template_properties.update({"ebs_optimized": True})
        if isinstance(compute_resource, SlurmComputeResource):
            conditional_template_properties.update({"instance_type": compute_resource.instance_types[0]})

        if queue.instance_profile:
            instance_profile_name = get_resource_name_from_resource_arn(queue.instance_profile)
            instance_role_name = (
                AWSApi.instance()
                .iam.get_instance_profile(instance_profile_name)
                .get("InstanceProfile")
                .get("Roles")[0]
                .get("RoleName")
            )
        elif queue.instance_role:
            instance_role_name = get_resource_name_from_resource_arn(queue.instance_role)
        else:
            instance_role_name = self.managed_compute_instance_roles[queue.name].ref

        launch_template_id = f"LaunchTemplate{create_hash_suffix(queue.name + compute_resource.name)}"
        compute_specific_dna_json_dict = {
            "cluster": {
                "cluster_name": self.stack_name,
                "stack_name": self.stack_name,
                "enable_efa": "efa" if compute_resource.efa and compute_resource.efa.enabled else "NONE",
                "ephemeral_dir": (
                    queue.compute_settings.local_storage.ephemeral_volume.mount_dir
                    if isinstance(queue, SlurmQueue) and queue.compute_settings.local_storage.ephemeral_volume
                    else DEFAULT_EPHEMERAL_DIR
                ),
                "proxy": queue.networking.proxy.http_proxy_address if queue.networking.proxy else "NONE",
                "node_type": "ComputeFleet",
                "scheduler_queue_name": queue.name,
                "scheduler_compute_resource_name": compute_resource.name,
                "enable_efa_gdr": ("compute" if compute_resource.efa and compute_resource.efa.gdr_support else "NONE"),
                "launch_template_id": launch_template_id,
            }
        }
        compute_specific_dna_json = json.dumps(compute_specific_dna_json_dict, indent=4)

        self._cluster_bucket.upload_dna_cfn_asset(
            file_type=S3FileType.COMPUTE_DNA_ASSETS,
            asset_file_content=compute_specific_dna_json_dict,
            asset_name=f"compute-dna-{launch_template_id}-{self._config.config_version}.json",
            format=S3FileFormat.JSON,
        )
        launch_template = ec2.CfnLaunchTemplate(
            self,
            launch_template_id,
            launch_template_name=f"{self.stack_name}-{queue.name}-{compute_resource.name}",
            launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
                block_device_mappings=self._launch_template_builder.get_block_device_mappings(
                    queue.compute_settings.local_storage.root_volume,
                    AWSApi.instance().ec2.describe_image(self._config.image_dict[queue.name]).device_name,
                ),
                # key_name=,
                network_interfaces=compute_lt_nw_interfaces,
                placement=ec2.CfnLaunchTemplate.PlacementProperty(group_name=placement_group),
                image_id=self._config.image_dict[queue.name],
                iam_instance_profile=ec2.CfnLaunchTemplate.IamInstanceProfileProperty(
                    name=instance_profiles[queue.name]
                ),
                instance_market_options=self._launch_template_builder.get_instance_market_options(
                    queue, compute_resource
                ),
                instance_initiated_shutdown_behavior="terminate",
                capacity_reservation_specification=self._launch_template_builder.get_capacity_reservation(
                    queue,
                    compute_resource,
                ),
                metadata_options=ec2.CfnLaunchTemplate.MetadataOptionsProperty(
                    http_tokens=get_http_tokens_setting(self._config.imds.imds_support)
                ),
                user_data=Fn.base64(
                    Fn.sub(
                        get_user_data_content("../resources/compute_node/user_data.sh"),
                        {
                            **{
                                # Disable multithreading using logic from
                                # https://aws.amazon.com/blogs/compute/disabling-intel-hyper-threading-technology-on-amazon-linux/
                                # thread_siblings_list contains a comma (,) or dash (-) separated list of CPU hardware
                                # threads within the same core as cpu
                                # e.g. 0-1 or 0,1
                                # cat /sys/devices/system/cpu/cpu*/topology/thread_siblings_list
                                #     | tr '-' ','       # convert hyphen (-) to comma (,), to account that
                                #                        # some kernels and CPU architectures use a hyphen
                                #                        # instead of a comma
                                #     | cut -s -d, -f2-  # split over comma (,) and take the right part
                                #     | tr ',' '\n'      # convert remaining comma (,) into new lines
                                #     | sort -un         # sort and unique
                                "DisableMultiThreadingManually": (
                                    "true" if compute_resource.disable_simultaneous_multithreading_manually else "false"
                                ),
                                "BaseOS": self._config.image.os,
                                "OSUser": OS_MAPPING[self._config.image.os]["user"],
                                "ClusterName": self.stack_name,
                                "Timeout": str(
                                    get_attr(
                                        self._config,
                                        "dev_settings.timeouts.compute_node_bootstrap_timeout",
                                        NODE_BOOTSTRAP_TIMEOUT,
                                    )
                                ),
                                "ComputeStartupTimeMetricEnabled": str(
                                    get_attr(
                                        self._config,
                                        "dev_settings.compute_startup_time_metric_enabled",
                                        default=False,
                                    )
                                ),
                                "LaunchTemplateResourceId": launch_template_id,
                                "CloudFormationUrl": get_service_endpoint("cloudformation", self._config.region),
                                "CfnInitRole": instance_role_name,
                                "ClusterConfigVersion": self._config.config_version,
                                "S3_BUCKET": self._cluster_bucket.name,
                                "S3_ARTIFACT_DIR": self._cluster_bucket.artifact_directory,
                            },
                            **get_common_user_data_env(queue, self._config),
                        },
                    )
                ),
                monitoring=ec2.CfnLaunchTemplate.MonitoringProperty(enabled=is_detailed_monitoring_enabled),
                tag_specifications=[
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="instance",
                        tags=get_default_instance_tags(
                            self.stack_name, self._config, compute_resource, "Compute", self._shared_storage_infos
                        )
                        + [CfnTag(key=PCLUSTER_QUEUE_NAME_TAG, value=queue.name)]
                        + [CfnTag(key=PCLUSTER_COMPUTE_RESOURCE_NAME_TAG, value=compute_resource.name)]
                        + self._get_custom_compute_resource_tags(queue, compute_resource),
                    ),
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="volume",
                        tags=get_default_volume_tags(self.stack_name, "Compute")
                        + [CfnTag(key=PCLUSTER_QUEUE_NAME_TAG, value=queue.name)]
                        + [CfnTag(key=PCLUSTER_COMPUTE_RESOURCE_NAME_TAG, value=compute_resource.name)]
                        + self._get_custom_compute_resource_tags(queue, compute_resource),
                    ),
                ],
                **conditional_template_properties,
            ),
        )

        common_dna_json = json.dumps(
            {
                "cluster": {
                    "stack_name": self.stack_name,
                    "raid_shared_dir": to_comma_separated_string(
                        self._shared_storage_mount_dirs[SharedStorageType.RAID]
                    ),
                    "raid_type": to_comma_separated_string(
                        self._shared_storage_attributes[SharedStorageType.RAID]["Type"]
                    ),
                    "base_os": self._config.image.os,
                    "region": self._config.region,
                    "shared_storage_type": self._config.head_node.shared_storage_type.lower(),
                    "default_user_home": (
                        self._config.deployment_settings.default_user_home.lower()
                        if (
                            self._config.deployment_settings is not None
                            and self._config.deployment_settings.default_user_home is not None
                        )
                        else DefaultUserHomeType.SHARED.value.lower()
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
                        self._shared_storage_attributes[SharedStorageType.EFS]["IamAuthorizations"], use_lower_case=True
                    ),
                    "efs_access_point_ids": to_comma_separated_string(
                        self._shared_storage_attributes[SharedStorageType.EFS]["AccessPointIds"],
                        use_lower_case=True,
                    ),
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
                    "scheduler": self._config.scheduling.scheduler,
                    "ebs_shared_dirs": to_comma_separated_string(
                        self._shared_storage_mount_dirs[SharedStorageType.EBS]
                    ),
                    "cluster_user": OS_MAPPING[self._config.image.os]["user"],
                    "log_group_name": (
                        self._log_group.log_group_name if self._config.monitoring.logs.cloud_watch.enabled else "NONE"
                    ),
                    "cw_logging_enabled": "true" if self._config.is_cw_logging_enabled else "false",
                    "log_rotation_enabled": "true" if self._config.is_log_rotation_enabled else "false",
                    "cluster_s3_bucket": self._cluster_bucket.name,
                    "cluster_config_s3_key": "{0}/configs/{1}".format(
                        self._cluster_bucket.artifact_directory, PCLUSTER_S3_ARTIFACTS_DICT.get("config_name")
                    ),
                    "cluster_config_version": self._config.config_version,
                    "custom_node_package": self._config.custom_node_package or "",
                    "custom_awsbatchcli_package": self._config.custom_aws_batch_cli_package or "",
                    "head_node_private_ip": self._head_eni.attr_primary_private_ip_address,
                    "disable_sudo_access_for_default_user": (
                        "true"
                        if self._config.deployment_settings
                        and self._config.deployment_settings.disable_sudo_access_default_user
                        else "false"
                    ),
                    "directory_service": {"enabled": str(self._config.directory_service is not None).lower()},
                    "dns_domain": str(self._cluster_hosted_zone.name) if self._cluster_hosted_zone else "",
                    "hosted_zone": str(self._cluster_hosted_zone.ref) if self._cluster_hosted_zone else "",
                    "slurm_ddb_table": self._dynamodb_table.ref if self._dynamodb_table else "NONE",
                    "use_private_hostname": str(
                        get_attr(self._config, "scheduling.settings.dns.use_ec2_hostnames", default=False)
                    ).lower(),
                },
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
                    # This file is never created. Keeping the content as config version to signify an Update for cfn-hup
                    "/tmp/common-dna.json": {  # nosec B108
                        "mode": "000644",
                        "owner": "root",
                        "group": "root",
                        "content": common_dna_json,
                    },
                    # A nosec comment is appended to the following line in order to disable the B108 check.
                    # The file is needed by the product
                    # [B108:hardcoded_tmp_directory] Probable insecure usage of temp file/directory.
                    "/tmp/compute-dna.json": {  # nosec B108
                        "content": compute_specific_dna_json,
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
                            'jq -s ".[0] * .[1] * .[2] * .[3]" /tmp/common-dna.json /tmp/compute-dna.json '
                            "/tmp/stack-arn.json /tmp/extra.json > /etc/chef/dna.json"
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
