# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as awslambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_route53 as route53
from aws_cdk import core

from pcluster.constants import OS_MAPPING
from pcluster.models.cluster_config import (
    CapacityType,
    ClusterBucket,
    CustomActionEvent,
    SharedStorageType,
    SlurmClusterConfig,
)
from pcluster.templates.cdk_builder_utils import (
    PclusterLambdaConstruct,
    add_lambda_cfn_role,
    cluster_name,
    create_hash_suffix,
    get_block_device_mappings,
    get_cloud_watch_logs_policy_statement,
    get_common_user_data_env,
    get_custom_tags,
    get_default_instance_tags,
    get_default_volume_tags,
    get_queue_security_groups_full,
    get_shared_storage_ids_by_type,
    get_shared_storage_options_by_type,
    get_user_data_content,
)


class SlurmConstruct(core.Construct):
    """Create the resources required when using Slurm as a scheduler."""

    def __init__(
        self,
        scope: core.Construct,
        id: str,
        stack_name: str,
        cluster_config: SlurmClusterConfig,
        bucket: ClusterBucket,
        dynamodb_table: dynamodb.CfnTable,
        log_group: logs.CfnLogGroup,
        instance_roles: dict,
        instance_profiles: dict,
        cleanup_lambda_role: iam.CfnRole,
        cleanup_lambda: awslambda.CfnFunction,
        compute_security_groups: dict,
        shared_storage_mappings: dict,
        shared_storage_options: dict,
        **kwargs,
    ):
        super().__init__(scope, id)
        self.stack_scope = scope
        self.stack_name = stack_name
        self.config = cluster_config
        self.bucket = bucket
        self.dynamodb_table = dynamodb_table
        self.log_group = log_group
        self.instance_roles = instance_roles
        self.instance_profiles = instance_profiles
        self.cleanup_lambda_role = cleanup_lambda_role
        self.cleanup_lambda = cleanup_lambda
        self.compute_security_groups = compute_security_groups
        self.shared_storage_mappings = shared_storage_mappings
        self.shared_storage_options = shared_storage_options

        self._add_resources()

    # -- Utility methods --------------------------------------------------------------------------------------------- #

    @property
    def _stack_region(self):
        return core.Stack.of(self).region

    @property
    def _stack_account(self):
        return core.Stack.of(self).account

    def _stack_unique_id(self):
        return core.Fn.select(2, core.Fn.split("/", core.Stack.of(self).stack_id))

    def _format_arn(self, **kwargs):
        return core.Stack.of(self).format_arn(**kwargs)

    # -- Resources --------------------------------------------------------------------------------------------------- #

    def _add_resources(self):
        # Add Slurm Policies to new instances roles
        for node_name, role_info in self.instance_roles.items():
            if role_info.get("IsNew"):
                self._add_policies_to_role(node_name, role_info.get("RoleRef"))

        if self.cleanup_lambda_role:
            self._add_policies_to_cleanup_resources_lambda_role()

        self._add_update_waiter_lambda()

        self._add_slurm_compute_fleet()

    def _add_policies_to_role(self, node_name, role):
        suffix = create_hash_suffix(node_name)

        iam.CfnPolicy(
            scope=self.stack_scope,
            id=f"SlurmPolicies{suffix}",
            policy_name="parallelcluster-slurm",
            policy_document=iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        sid="EC2Terminate",
                        effect=iam.Effect.ALLOW,
                        actions=["ec2:TerminateInstances"],
                        resources=["*"],
                        conditions={"StringEquals": {"ec2:ResourceTag/Application": self.stack_name}},
                    ),
                    iam.PolicyStatement(
                        sid="EC2",
                        effect=iam.Effect.ALLOW,
                        actions=[
                            "ec2:DescribeInstances",
                            "ec2:DescribeLaunchTemplates",
                            "ec2:RunInstances",
                            "ec2:DescribeInstanceStatus",
                            "ec2:CreateTags",
                        ],
                        resources=["*"],
                    ),
                    iam.PolicyStatement(
                        sid="ResourcesS3Bucket",
                        effect=iam.Effect.ALLOW,
                        actions=["s3:ListBucket", "s3:ListBucketVersions", "s3:GetObject*", "s3:PutObject*"]
                        if self.bucket.remove_on_deletion
                        else ["s3:*"],
                        resources=[
                            self._format_arn(service="s3", resource=self.bucket.name, region="", account=""),
                            self._format_arn(
                                service="s3",
                                resource=f"{self.bucket.name}/{self.bucket.artifact_directory}/*",
                                region="",
                                account="",
                            ),
                        ],
                    ),
                    iam.PolicyStatement(
                        sid="DynamoDBTableQuery",
                        effect=iam.Effect.ALLOW,
                        actions=["dynamodb:Query"],
                        resources=[
                            self._format_arn(service="dynamodb", resource="table/{0}".format(self.stack_name)),
                            self._format_arn(service="dynamodb", resource="table/{0}/index/*".format(self.stack_name)),
                        ],
                    ),
                ]
            ),
            roles=[role],
        )

    def _add_policies_to_cleanup_resources_lambda_role(self):
        self.cleanup_lambda_role.policies[0].policy_document.add_statements(
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
                conditions={"StringEquals": {"ec2:ResourceTag/Application": self.stack_name}},
                sid="FleetTerminatePolicy",
            ),
        )

    def _add_slurm_compute_fleet(self):

        self.cluster_hosted_zone = None
        if not self._condition_disable_cluster_dns():
            self.cluster_hosted_zone = self._add_private_hosted_zone()

        for queue in self.config.scheduling.queues:
            queue_lt_security_groups = get_queue_security_groups_full(self.compute_security_groups, queue)

            queue_placement_group = None
            if queue.networking.placement_group and queue.networking.placement_group.enabled:
                if queue.networking.placement_group.id:
                    queue_placement_group = queue.networking.placement_group.id
                else:
                    # Create Placement Group
                    queue_placement_group = ec2.CfnPlacementGroup(
                        scope=self.stack_scope, id=f"PlacementGroup{create_hash_suffix(queue.name)}", strategy="cluster"
                    ).ref

            queue_pre_install_action = queue.get_custom_action(event=CustomActionEvent.NODE_START)
            queue_post_install_action = queue.get_custom_action(event=CustomActionEvent.NODE_CONFIGURED)

            for compute_resource in queue.compute_resources:
                instance_type = compute_resource.instance_type

                self._add_compute_resource_launch_template(
                    queue,
                    compute_resource,
                    instance_type,
                    queue_pre_install_action,
                    queue_post_install_action,
                    queue_lt_security_groups,
                    queue_placement_group,
                )

        core.CustomResource(
            scope=self.stack_scope,
            id="TerminateComputeFleetCustomResource",
            service_token=self.cleanup_lambda.attr_arn,
            properties={"StackName": self.stack_name, "Action": "TERMINATE_EC2_INSTANCES"},
        )
        # TODO: add depends_on resources from CloudWatchLogsSubstack and ComputeFleetHitSubstack?
        # terminate_compute_fleet_custom_resource.add_depends_on()

        core.CfnOutput(
            scope=self.stack_scope,
            id="ConfigVersion",
            description="Version of the config used to generate the stack",
            value=self.config.config_version,
        )

    def _add_private_hosted_zone(self):
        cluster_hosted_zone = route53.CfnHostedZone(
            scope=self.stack_scope,
            id="Route53HostedZone",
            name=f"{cluster_name(self.stack_name)}.pcluster",
            vpcs=[route53.CfnHostedZone.VPCProperty(vpc_id=self.config.vpc_id, vpc_region=self._stack_region)],
        )

        head_node_role_info = self.instance_roles.get("HeadNode")
        if head_node_role_info.get("IsNew"):
            iam.CfnPolicy(
                scope=self.stack_scope,
                id="ParallelClusterSlurmRoute53Policies",
                policy_name="parallelcluster-slurm-route53",
                policy_document=iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="Route53Add",
                            effect=iam.Effect.ALLOW,
                            actions=["route53:ChangeResourceRecordSets"],
                            resources=[
                                self._format_arn(
                                    service="route53",
                                    region="",
                                    account="",
                                    resource=f"hostedzone/{cluster_hosted_zone.ref}",
                                ),
                            ],
                        ),
                    ]
                ),
                roles=[head_node_role_info.get("RoleRef")],
            )

        cleanup_route53_lambda_execution_role = None
        if self.cleanup_lambda_role:
            cleanup_route53_lambda_execution_role = add_lambda_cfn_role(
                scope=self.stack_scope,
                function_id="CleanupRoute53",
                statements=[
                    iam.PolicyStatement(
                        actions=["route53:ListResourceRecordSets", "route53:ChangeResourceRecordSets"],
                        effect=iam.Effect.ALLOW,
                        resources=[
                            self._format_arn(
                                service="route53",
                                region="",
                                account="",
                                resource=f"hostedzone/{cluster_hosted_zone.ref}",
                            ),
                        ],
                        sid="Route53DeletePolicy",
                    ),
                    get_cloud_watch_logs_policy_statement(
                        resource=self._format_arn(service="logs", account="*", region="*", resource="*")
                    ),
                ],
            )

        cleanup_route53_lambda = PclusterLambdaConstruct(
            scope=self.stack_scope,
            id="CleanupRoute53FunctionConstruct",
            function_id="CleanupRoute53",
            bucket=self.bucket,
            config=self.config,
            execution_role=cleanup_route53_lambda_execution_role.attr_arn
            if cleanup_route53_lambda_execution_role
            else self._format_arn(
                service="iam",
                region="",
                resource="role/{0}".format(self.config.iam.roles.custom_lambda_resources),
                account=self._stack_account,
            ),
            handler_func="cleanup_resources",
        ).lambda_func

        core.CustomResource(
            scope=self.stack_scope,
            id="CleanupRoute53CustomResource",
            service_token=cleanup_route53_lambda.attr_arn,
            properties={"ClusterHostedZone": cluster_hosted_zone.ref, "Action": "DELETE_DNS_RECORDS"},
        )

        core.CfnOutput(
            scope=self.stack_scope,
            id="ClusterHostedZone",
            description="Id of the private hosted zone created within the cluster",
            value=cluster_hosted_zone.ref,
        )
        core.CfnOutput(
            scope=self.stack_scope,
            id="ClusterDNSDomain",
            description="DNS Domain of the private hosted zone created within the cluster",
            value=cluster_hosted_zone.name,
        )

        return cluster_hosted_zone

    def _add_update_waiter_lambda(self):
        update_waiter_lambda_execution_role = None
        if self.cleanup_lambda_role:
            update_waiter_lambda_execution_role = add_lambda_cfn_role(
                scope=self.stack_scope,
                function_id="UpdateWaiter",
                statements=[
                    iam.PolicyStatement(
                        actions=["dynamodb:GetItem", "dynamodb:PutItem"],
                        effect=iam.Effect.ALLOW,
                        resources=[
                            self._format_arn(
                                service="dynamodb",
                                account=self._stack_account,
                                resource=f"table/{self.dynamodb_table.ref}",
                            ),
                        ],
                        sid="DynamoDBTable",
                    ),
                    get_cloud_watch_logs_policy_statement(
                        resource=self._format_arn(service="logs", account="*", region="*", resource="*")
                    ),
                ],
            )

        update_waiter_lambda = PclusterLambdaConstruct(
            scope=self.stack_scope,
            id="UpdateWaiterFunctionConstruct",
            function_id="UpdateWaiter",
            bucket=self.bucket,
            config=self.config,
            execution_role=update_waiter_lambda_execution_role.attr_arn
            if update_waiter_lambda_execution_role
            else self._format_arn(
                service="iam",
                account=self._stack_account,
                resource="role/{0}".format(self.config.iam.roles.custom_lambda_resources),
                region="",
            ),
            handler_func="wait_for_update",
        ).lambda_func

        core.CustomResource(
            self.stack_scope,
            "UpdateWaiterCustomResource",
            service_token=update_waiter_lambda.attr_arn,
            properties={
                "ConfigVersion": self.config.config_version,
                "DynamoDBTable": self.dynamodb_table.ref,
            },
        )

        core.CfnOutput(scope=self.stack_scope, id="UpdateWaiterFunctionArn", value=update_waiter_lambda.attr_arn)

    def _add_compute_resource_launch_template(
        self,
        queue,
        compute_resource,
        instance_type,
        queue_pre_install_action,
        queue_post_install_action,
        queue_lt_security_groups,
        queue_placement_group,
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
                subnet_id=queue.networking.subnet_ids[0],
            )
        ]
        for device_index in range(1, compute_resource.max_network_interface_count):
            compute_lt_nw_interfaces.append(
                ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                    device_index=device_index,
                    network_card_index=device_index,
                    interface_type="efa" if compute_resource.efa and compute_resource.efa.enabled else None,
                    groups=queue_lt_security_groups,
                    subnet_id=queue.networking.subnet_ids[0],
                )
            )

        instance_market_options = None
        if queue.capacity_type == CapacityType.SPOT:
            instance_market_options = ec2.CfnLaunchTemplate.InstanceMarketOptionsProperty(
                market_type="spot",
                spot_options=ec2.CfnLaunchTemplate.SpotOptionsProperty(
                    spot_instance_type="one-time",
                    instance_interruption_behavior="terminate",
                    max_price=compute_resource.spot_price,
                ),
            )

        ec2.CfnLaunchTemplate(
            scope=self.stack_scope,
            id=f"ComputeServerLaunchTemplate{create_hash_suffix(queue.name + instance_type)}",
            launch_template_name=f"{cluster_name(self.stack_name)}-{queue.name}-{instance_type}",
            launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
                instance_type=instance_type,
                cpu_options=ec2.CfnLaunchTemplate.CpuOptionsProperty(
                    core_count=compute_resource.vcpus, threads_per_core=1
                )
                if compute_resource.pass_cpu_options_in_launch_template
                else None,
                block_device_mappings=get_block_device_mappings(queue, self.config.image.os),
                # key_name=,
                network_interfaces=compute_lt_nw_interfaces,
                placement=ec2.CfnLaunchTemplate.PlacementProperty(group_name=queue_placement_group),
                image_id=self.config.ami_id,
                ebs_optimized=compute_resource.is_ebs_optimized,
                iam_instance_profile=ec2.CfnLaunchTemplate.IamInstanceProfileProperty(
                    name=self.instance_profiles[queue.name]
                ),
                instance_market_options=instance_market_options,
                user_data=core.Fn.base64(
                    core.Fn.sub(
                        get_user_data_content("../resources/compute_node/user_data.sh"),
                        {
                            **{
                                "IamRoleName": str(self.instance_roles[queue.name]["RoleRef"]),
                                "EnableEfa": "efa" if compute_resource.efa and compute_resource.efa.enabled else "NONE",
                                "RAIDOptions": get_shared_storage_options_by_type(
                                    self.shared_storage_options, SharedStorageType.RAID
                                ),
                                "DisableHyperThreadingManually": "true"
                                if compute_resource.disable_simultaneous_multithreading_manually
                                else "false",
                                "BaseOS": self.config.image.os,
                                "PreInstallScript": queue_pre_install_action.script
                                if queue_pre_install_action
                                else "NONE",
                                "PreInstallArgs": queue_pre_install_action.args
                                if queue_pre_install_action and queue_pre_install_action.args
                                else "NONE",
                                "PostInstallScript": queue_post_install_action.script
                                if queue_post_install_action
                                else "NONE",
                                "PostInstallArgs": queue_post_install_action.args
                                if queue_post_install_action and queue_post_install_action.args
                                else "NONE",
                                "EFSId": get_shared_storage_ids_by_type(
                                    self.shared_storage_mappings, SharedStorageType.EFS
                                ),
                                "EFSOptions": get_shared_storage_options_by_type(
                                    self.shared_storage_options, SharedStorageType.EFS
                                ),  # FIXME
                                "FSXId": get_shared_storage_ids_by_type(
                                    self.shared_storage_mappings, SharedStorageType.FSX
                                ),
                                "FSXOptions": get_shared_storage_options_by_type(
                                    self.shared_storage_options, SharedStorageType.FSX
                                ),
                                "Scheduler": self.config.scheduling.scheduler,
                                "EncryptedEphemeral": "true"
                                if queue.compute_settings
                                and queue.compute_settings.local_storage
                                and queue.compute_settings.local_storage.ephemeral_volume
                                and queue.compute_settings.local_storage.ephemeral_volume.encrypted
                                else "NONE",
                                "EphemeralDir": queue.compute_settings.local_storage.ephemeral_volume.mount_dir
                                if queue.compute_settings
                                and queue.compute_settings.local_storage
                                and queue.compute_settings.local_storage.ephemeral_volume
                                else "/scratch",
                                "EbsSharedDirs": get_shared_storage_options_by_type(
                                    self.shared_storage_options, SharedStorageType.EBS
                                ),
                                "ClusterDNSDomain": str(self.cluster_hosted_zone.name)
                                if self.cluster_hosted_zone
                                else "",
                                "ClusterHostedZone": str(self.cluster_hosted_zone.ref)
                                if self.cluster_hosted_zone
                                else "",
                                "OSUser": OS_MAPPING[self.config.image.os]["user"],
                                "DynamoDBTable": self.dynamodb_table.ref,
                                "LogGroupName": self.log_group.log_group_name
                                if self.config.monitoring.logs.cloud_watch.enabled
                                else "NONE",
                                "IntelHPCPlatform": "true" if self.config.is_intel_hpc_platform_enabled else "false",
                                "CWLoggingEnabled": "true" if self.config.is_cw_logging_enabled else "false",
                                "QueueName": queue.name,
                                "EnableEfaGdr": "compute"
                                if compute_resource.efa and compute_resource.efa.gdr_support
                                else "NONE",
                                "ExtraJson": self.config.extra_chef_attributes,
                            },
                            **get_common_user_data_env(queue, self.config),
                        },
                    )
                ),
                monitoring=ec2.CfnLaunchTemplate.MonitoringProperty(enabled=False),
                tag_specifications=[
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="instance",
                        tags=get_default_instance_tags(
                            self.stack_name, self.config, compute_resource, "Compute", self.shared_storage_mappings
                        )
                        + [core.CfnTag(key="QueueName", value=queue.name)]
                        + get_custom_tags(self.config),
                    ),
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="volume",
                        tags=get_default_volume_tags(self.stack_name, "Compute")
                        + [core.CfnTag(key="QueueName", value=queue.name)]
                        + get_custom_tags(self.config),
                    ),
                ],
            ),
        )

    # -- Conditions -------------------------------------------------------------------------------------------------- #

    def _condition_disable_cluster_dns(self):
        return (
            self.config.scheduling.settings
            and self.config.scheduling.settings.dns
            and self.config.scheduling.settings.dns.disable_managed_dns
        )
