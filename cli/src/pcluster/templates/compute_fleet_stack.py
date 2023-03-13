# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=too-many-lines

#
# This module contains all the classes required to convert a Cluster into a CFN template by using CDK.
#
from typing import Dict, List

from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as awslambda
from aws_cdk import aws_logs as logs
from aws_cdk.core import CfnCustomResource, CfnResource, CfnTag, Construct, Fn, NestedStack, Stack

from pcluster.config.cluster_config import (
    SchedulerPluginQueue,
    SharedStorageType,
    SlurmClusterConfig,
    SlurmComputeResource,
    SlurmQueue,
)
from pcluster.constants import (
    DEFAULT_EPHEMERAL_DIR,
    NODE_BOOTSTRAP_TIMEOUT,
    OS_MAPPING,
    PCLUSTER_CLUSTER_NAME_TAG,
    PCLUSTER_COMPUTE_RESOURCE_NAME_TAG,
    PCLUSTER_QUEUE_NAME_TAG,
)
from pcluster.templates.cdk_builder_utils import (
    CdkLaunchTemplateBuilder,
    ComputeNodeIamResources,
    create_hash_suffix,
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
from pcluster.utils import get_attr, get_http_tokens_setting, join_shell_args


class ComputeFleetStack(NestedStack):
    """Construct defining compute fleet specific resources."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        cluster_config: SlurmClusterConfig,
        log_group: logs.CfnLogGroup,
        cleanup_lambda: awslambda.CfnFunction,
        cleanup_lambda_role: iam.CfnRole,
        compute_security_group: ec2.CfnSecurityGroup,
        shared_storage_infos: Dict,
        shared_storage_mount_dirs: Dict,
        shared_storage_attributes: Dict,
        cluster_hosted_zone,
        dynamodb_table,
        head_eni,
        slurm_construct: SlurmConstruct,
    ):
        super().__init__(scope, id)
        self._cleanup_lambda = cleanup_lambda
        self._cleanup_lambda_role = cleanup_lambda_role
        self._compute_security_group = compute_security_group
        self._config = cluster_config
        self._shared_storage_infos = shared_storage_infos
        self._shared_storage_mount_dirs = shared_storage_mount_dirs
        self._shared_storage_attributes = shared_storage_attributes
        self._log_group = log_group
        self._cluster_hosted_zone = cluster_hosted_zone
        self._dynamodb_table = dynamodb_table
        self._head_eni = head_eni
        self._launch_template_builder = CdkLaunchTemplateBuilder()
        self._slurm_construct = slurm_construct
        self._add_resources()

    # -- Utility methods --------------------------------------------------------------------------------------------- #

    @property
    def stack_name(self):
        """Name of the CFN stack."""
        return Stack.of(self.nested_stack_parent).stack_name

    # -- Resources --------------------------------------------------------------------------------------------------- #

    def _add_compute_iam_resources(self):
        iam_resources = {}
        for queue in self._config.scheduling.queues:
            iam_resources[queue.name] = ComputeNodeIamResources(
                self,
                f"ComputeNodeIamResources{queue.name}",
                self._config,
                queue,
                self._shared_storage_infos,
                queue.name,
            )
        self._compute_instance_profiles = {k: v.instance_profile for k, v in iam_resources.items()}
        self._managed_compute_instance_roles = {k: v.instance_role for k, v in iam_resources.items()}
        if scheduler_is_slurm(self._config):
            self._slurm_construct.register_policies_with_role(
                scope=Stack.of(self),
                managed_compute_instance_roles=self._managed_compute_instance_roles,
            )

    @property
    def managed_compute_instance_roles(self) -> Dict[str, iam.Role]:
        """Mapping of each queue and the IAM role associated with its compute resources."""
        return self._managed_compute_instance_roles

    def _add_resources(self):
        self._add_compute_iam_resources()
        managed_placement_groups = self._add_placement_groups()
        self.compute_launch_templates = self._add_launch_templates(
            managed_placement_groups, self._compute_instance_profiles
        )
        custom_resource_deps = list(managed_placement_groups.values())
        if self._compute_security_group:
            custom_resource_deps.append(self._compute_security_group)
        self._add_cleanup_custom_resource(dependencies=custom_resource_deps)

    def _add_cleanup_custom_resource(self, dependencies: List[CfnResource]):
        terminate_compute_fleet_custom_resource = CfnCustomResource(
            self,
            "TerminateComputeFleetCustomResource",
            service_token=self._cleanup_lambda.attr_arn,
        )
        terminate_compute_fleet_custom_resource.add_property_override("StackName", self.stack_name)
        terminate_compute_fleet_custom_resource.add_property_override("Action", "TERMINATE_EC2_INSTANCES")
        for dep in dependencies:
            terminate_compute_fleet_custom_resource.add_depends_on(dep)

        if self._cleanup_lambda_role:
            self._add_policies_to_cleanup_resources_lambda_role()

    def _add_policies_to_cleanup_resources_lambda_role(self):
        self._cleanup_lambda_role.policies[0].policy_document.add_statements(
            iam.PolicyStatement(
                actions=["ec2:DescribeInstances"],
                resources=["*"],
                effect=iam.Effect.ALLOW,
                sid="DescribeInstances",
            ),
            iam.PolicyStatement(
                actions=["ec2:TerminateInstances"],
                resources=["*"],
                effect=iam.Effect.ALLOW,
                conditions={"StringEquals": {f"ec2:ResourceTag/{PCLUSTER_CLUSTER_NAME_TAG}": self.stack_name}},
                sid="FleetTerminatePolicy",
            ),
        )

    def _add_placement_groups(self) -> Dict[str, ec2.CfnPlacementGroup]:
        managed_placement_groups = {}
        for queue in self._config.scheduling.queues:
            for key in queue.get_managed_placement_group_keys():
                managed_placement_groups[key] = ec2.CfnPlacementGroup(
                    self,
                    f"PlacementGroup{create_hash_suffix(key)}",
                    strategy="cluster",
                )
        return managed_placement_groups

    @staticmethod
    def _get_placement_group_for_compute_resource(queue, managed_placement_groups, compute_resource) -> str:
        placement_group_settings = queue.get_placement_group_settings_for_compute_resource(compute_resource)
        placement_group_key = placement_group_settings.get("key")
        managed = placement_group_settings.get("is_managed")
        return managed_placement_groups[placement_group_key].ref if managed else placement_group_key

    def _add_launch_templates(self, managed_placement_groups, instance_profiles):
        compute_launch_templates = {}
        for queue in self._config.scheduling.queues:
            compute_launch_templates[queue.name] = {}
            queue_lt_security_groups = get_queue_security_groups_full(self._compute_security_group, queue)
            queue_pre_install_action, queue_post_install_action = (None, None)
            if queue.custom_actions:
                queue_pre_install_action = queue.custom_actions.on_node_start
                queue_post_install_action = queue.custom_actions.on_node_configured

            for resource in queue.compute_resources:
                compute_launch_templates[queue.name][resource.name] = self._add_compute_resource_launch_template(
                    queue,
                    resource,
                    queue_pre_install_action,
                    queue_post_install_action,
                    queue_lt_security_groups,
                    self._get_placement_group_for_compute_resource(queue, managed_placement_groups, resource),
                    instance_profiles,
                )
        return compute_launch_templates

    def _add_compute_resource_launch_template(
        self,
        queue,
        compute_resource,
        queue_pre_install_action,
        queue_post_install_action,
        queue_lt_security_groups,
        placement_group,
        instance_profiles,
    ):
        # LT network interfaces
        compute_lt_nw_interfaces = [
            ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                device_index=0,
                associate_public_ip_address=queue.networking.assign_public_ip
                if compute_resource.max_network_interface_count == 1
                else None,  # parameter not supported for instance types with multiple network interfaces
                interface_type="efa" if compute_resource.efa and compute_resource.efa.enabled else None,
                groups=queue_lt_security_groups,
                subnet_id=queue.networking.subnet_ids[0]
                if isinstance(compute_resource, SlurmComputeResource)
                else None,
            )
        ]

        for network_interface_index in range(1, compute_resource.max_network_interface_count):
            compute_lt_nw_interfaces.append(
                ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                    device_index=0,
                    network_card_index=network_interface_index,
                    interface_type="efa" if compute_resource.efa and compute_resource.efa.enabled else None,
                    groups=queue_lt_security_groups,
                    subnet_id=queue.networking.subnet_ids[0]
                    if isinstance(compute_resource, SlurmComputeResource)
                    else None,
                )
            )

        conditional_template_properties = {}
        if compute_resource.is_ebs_optimized:
            conditional_template_properties.update({"ebs_optimized": True})
        if isinstance(compute_resource, SlurmComputeResource):
            conditional_template_properties.update({"instance_type": compute_resource.instance_type})

        return ec2.CfnLaunchTemplate(
            self,
            f"LaunchTemplate{create_hash_suffix(queue.name + compute_resource.name)}",
            launch_template_name=f"{self.stack_name}-{queue.name}-{compute_resource.name}",
            launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
                block_device_mappings=self._launch_template_builder.get_block_device_mappings(
                    queue.compute_settings.local_storage.root_volume, self._config.image.os
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
                                "EnableEfa": "efa" if compute_resource.efa and compute_resource.efa.enabled else "NONE",
                                "RAIDSharedDir": to_comma_separated_string(
                                    self._shared_storage_mount_dirs[SharedStorageType.RAID]
                                ),
                                "RAIDType": to_comma_separated_string(
                                    self._shared_storage_attributes[SharedStorageType.RAID]["Type"]
                                ),
                                "DisableMultiThreadingManually": "true"
                                if compute_resource.disable_simultaneous_multithreading_manually
                                else "false",
                                "BaseOS": self._config.image.os,
                                "PreInstallScript": queue_pre_install_action.script
                                if queue_pre_install_action
                                else "NONE",
                                "PreInstallArgs": join_shell_args(queue_pre_install_action.args)
                                if queue_pre_install_action and queue_pre_install_action.args
                                else "NONE",
                                "PostInstallScript": queue_post_install_action.script
                                if queue_post_install_action
                                else "NONE",
                                "PostInstallArgs": join_shell_args(queue_post_install_action.args)
                                if queue_post_install_action and queue_post_install_action.args
                                else "NONE",
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
                                "Scheduler": self._config.scheduling.scheduler,
                                "EphemeralDir": queue.compute_settings.local_storage.ephemeral_volume.mount_dir
                                if isinstance(queue, (SlurmQueue, SchedulerPluginQueue))
                                and queue.compute_settings.local_storage.ephemeral_volume
                                else DEFAULT_EPHEMERAL_DIR,
                                "EbsSharedDirs": to_comma_separated_string(
                                    self._shared_storage_mount_dirs[SharedStorageType.EBS]
                                ),
                                "ClusterDNSDomain": str(self._cluster_hosted_zone.name)
                                if self._cluster_hosted_zone
                                else "",
                                "ClusterHostedZone": str(self._cluster_hosted_zone.ref)
                                if self._cluster_hosted_zone
                                else "",
                                "OSUser": OS_MAPPING[self._config.image.os]["user"],
                                "SlurmDynamoDBTable": self._dynamodb_table.ref if self._dynamodb_table else "NONE",
                                "LogGroupName": self._log_group.log_group_name
                                if self._config.monitoring.logs.cloud_watch.enabled
                                else "NONE",
                                "IntelHPCPlatform": "true" if self._config.is_intel_hpc_platform_enabled else "false",
                                "CWLoggingEnabled": "true" if self._config.is_cw_logging_enabled else "false",
                                "LogRotationEnabled": "true" if self._config.is_log_rotation_enabled else "false",
                                "QueueName": queue.name,
                                "ComputeResourceName": compute_resource.name,
                                "EnableEfaGdr": "compute"
                                if compute_resource.efa and compute_resource.efa.gdr_support
                                else "NONE",
                                "CustomNodePackage": self._config.custom_node_package or "",
                                "CustomAwsBatchCliPackage": self._config.custom_aws_batch_cli_package or "",
                                "ExtraJson": self._config.extra_chef_attributes,
                                "UsePrivateHostname": str(
                                    get_attr(self._config, "scheduling.settings.dns.use_ec2_hostnames", default=False)
                                ).lower(),
                                "HeadNodePrivateIp": self._head_eni.attr_primary_private_ip_address,
                                "DirectoryServiceEnabled": str(self._config.directory_service is not None).lower(),
                                "Timeout": str(
                                    get_attr(
                                        self._config,
                                        "dev_settings.timeouts.compute_node_bootstrap_timeout",
                                        NODE_BOOTSTRAP_TIMEOUT,
                                    )
                                ),
                            },
                            **get_common_user_data_env(queue, self._config),
                        },
                    )
                ),
                monitoring=ec2.CfnLaunchTemplate.MonitoringProperty(enabled=False),
                tag_specifications=[
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="instance",
                        tags=get_default_instance_tags(
                            self.stack_name, self._config, compute_resource, "Compute", self._shared_storage_infos
                        )
                        + [CfnTag(key=PCLUSTER_QUEUE_NAME_TAG, value=queue.name)]
                        + [CfnTag(key=PCLUSTER_COMPUTE_RESOURCE_NAME_TAG, value=compute_resource.name)]
                        + get_custom_tags(self._config),
                    ),
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="volume",
                        tags=get_default_volume_tags(self.stack_name, "Compute")
                        + [CfnTag(key=PCLUSTER_QUEUE_NAME_TAG, value=queue.name)]
                        + [CfnTag(key=PCLUSTER_COMPUTE_RESOURCE_NAME_TAG, value=compute_resource.name)]
                        + get_custom_tags(self._config),
                    ),
                ],
                **conditional_template_properties,
            ),
        )
