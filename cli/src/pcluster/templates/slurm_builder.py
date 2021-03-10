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
from aws_cdk import aws_route53 as route53
from aws_cdk import core

from pcluster.constants import COOKBOOK_PACKAGES_VERSIONS, OS_MAPPING
from pcluster.models.cluster_config import (
    ClusterBucket,
    ComputeType,
    CustomActionEvent,
    SharedStorageType,
    SlurmClusterConfig,
)
from pcluster.templates.cdk_builder_utils import (
    cluster_name,
    create_hash_suffix,
    get_block_device_mappings,
    get_custom_tags,
    get_default_instance_tags,
    get_default_volume_tags,
    get_shared_storage_ids_by_type,
    get_shared_storage_options_by_type,
    get_user_data_content,
)

# pylint disable=R0801


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
        instance_roles: dict,
        instance_profiles: dict,
        cleanup_lambda_role: iam.CfnRole,
        cleanup_lambda: awslambda.CfnFunction,
        compute_security_group: ec2.CfnSecurityGroup,
        shared_storage_ids: dict,
        shared_storage_options: dict,
        **kwargs,
    ):
        super().__init__(scope, id)
        self.stack_name = stack_name
        self.config = cluster_config
        self.bucket = bucket
        self.dynamodb_table = dynamodb_table
        self.instance_roles = instance_roles
        self.instance_profiles = instance_profiles
        self.cleanup_lambda_role = cleanup_lambda_role
        self.cleanup_lambda = cleanup_lambda
        self.compute_security_group = compute_security_group
        self.shared_storage_ids = shared_storage_ids
        self.shared_storage_options = shared_storage_options

        self._add_resources()

    # -- Utility methods --------------------------------------------------------------------------------------------- #

    @property
    def _region(self):
        return core.Stack.of(self).region

    @property
    def _account(self):
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
            scope=self,
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

            # LT security groups
            queue_lt_security_groups = []
            if queue.networking.security_groups:
                queue_lt_security_groups.extend(queue.networking.security_groups)
            if queue.networking.additional_security_groups:
                queue_lt_security_groups.extend(queue.networking.additional_security_groups)
            if self.compute_security_group:
                queue_lt_security_groups.append(self.compute_security_group.ref)

            queue_placement_group = None
            if queue.networking.placement_group and queue.networking.placement_group.enabled:
                if queue.networking.placement_group.id:
                    queue_placement_group = queue.networking.placement_group.id
                else:
                    # Create Placement Group
                    queue_placement_group = ec2.CfnPlacementGroup(
                        scope=self, id=f"PlacementGroup{create_hash_suffix(queue.name)}", strategy="cluster"
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
            scope=self,
            id="TerminateComputeFleetCustomResource",
            service_token=self.cleanup_lambda.attr_arn,
            properties={"StackName": self.stack_name, "Action": "TERMINATE_EC2_INSTANCES"},
        )
        # TODO: add depends_on resources from CloudWatchLogsSubstack and ComputeFleetHitSubstack?
        # terminate_compute_fleet_custom_resource.add_depends_on()

        core.CfnOutput(
            scope=self,
            id="ConfigVersion",
            description="Version of the config used to generate the stack",
            value=self.config.config_version,
        )

    def _add_private_hosted_zone(self):
        cluster_hosted_zone = route53.CfnHostedZone(
            scope=self,
            id="Route53HostedZone",
            name=f"{cluster_name(self.stack_name)}.pcluster",
            vpcs=[route53.CfnHostedZone.VPCProperty(vpc_id=self.config.vpc_id, vpc_region=self._region)],
        )

        head_node_role_info = self.instance_roles.get("HeadNode")
        if head_node_role_info.get("IsNew"):
            iam.CfnPolicy(
                scope=self,
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
                                    resource=f"hostedzone/{cluster_hosted_zone.attr_id}",
                                ),
                            ],
                        ),
                    ]
                ),
                roles=[head_node_role_info.get("RoleRef")],
            )

        cleanup_route53_lambda_execution_role = None
        if self.cleanup_lambda_role:
            cleanup_route53_lambda_execution_role = iam.CfnRole(
                scope=self,
                id="CleanupRoute53FunctionExecutionRole",
                assume_role_policy_document=iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=["sts:AssumeRole"],
                            effect=iam.Effect.ALLOW,
                            principals=[iam.ServicePrincipal(service="lambda.amazonaws.com")],
                        )
                    ],
                ),
                path="/",
                policies=[
                    iam.CfnRole.PolicyProperty(
                        policy_document=iam.PolicyDocument(
                            statements=[
                                iam.PolicyStatement(
                                    actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                                    effect=iam.Effect.ALLOW,
                                    resources=[self._format_arn(service="logs", account="*", region="*", resource="*")],
                                    sid="CloudWatchLogsPolicy",
                                ),
                                iam.PolicyStatement(
                                    actions=["route53:ListResourceRecordSets", "route53:ChangeResourceRecordSets"],
                                    effect=iam.Effect.ALLOW,
                                    resources=[
                                        self._format_arn(
                                            service="route53",
                                            region="",
                                            account="",
                                            resource=f"hostedzone/{cluster_hosted_zone.attr_id}",
                                        ),
                                    ],
                                    sid="Route53DeletePolicy",
                                ),
                            ],
                        ),
                        policy_name="LambdaPolicy",
                    ),
                ],
            )

        cleanup_route53_lambda = awslambda.CfnFunction(
            scope=self,
            id="CleanupRoute53Function",
            function_name=f"pcluster-CleanupRoute53-{self._stack_unique_id()}",
            code=awslambda.CfnFunction.CodeProperty(
                s3_bucket=self.bucket.name,
                s3_key=f"{self.bucket.artifact_directory}/custom_resources_code/artifacts.zip",
            ),
            handler="cleanup_resources.handler",
            memory_size=128,
            role=cleanup_route53_lambda_execution_role.attr_arn
            if cleanup_route53_lambda_execution_role
            else self._format_arn(
                service="iam",
                region="",
                account=self._account,
                resource="role/{0}".format(self.config.iam.roles.custom_lambda_resources),
            ),
            runtime="python3.8",
            timeout=900,
        )

        core.CustomResource(
            scope=self,
            id="CleanupRoute53CustomResource",
            service_token=cleanup_route53_lambda.attr_arn,
            properties={"ClusterHostedZone": cluster_hosted_zone.attr_id, "Action": "DELETE_DNS_RECORDS"},
        )

        core.CfnOutput(
            scope=self,
            id="ClusterHostedZone",
            description="Id of the private hosted zone created within the cluster",
            value=cluster_hosted_zone.attr_id,
        )
        core.CfnOutput(
            scope=self,
            id="ClusterDNSDomain",
            description="DNS Domain of the private hosted zone created within the cluster",
            value=cluster_hosted_zone.name,
        )

        return cluster_hosted_zone

    def _add_update_waiter_lambda(self):
        update_waiter_lambda_execution_role = None
        if self.cleanup_lambda_role:
            update_waiter_lambda_execution_role = iam.CfnRole(
                scope=self,
                id="UpdateWaiterFunctionExecutionRole",
                assume_role_policy_document=iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=["sts:AssumeRole"],
                            effect=iam.Effect.ALLOW,
                            principals=[iam.ServicePrincipal(service="lambda.amazonaws.com")],
                        )
                    ],
                ),
                path="/",
                policies=[
                    iam.CfnRole.PolicyProperty(
                        policy_document=iam.PolicyDocument(
                            statements=[
                                iam.PolicyStatement(
                                    actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                                    effect=iam.Effect.ALLOW,
                                    resources=[self._format_arn(service="logs", account="*", region="*", resource="*")],
                                    sid="CloudWatchLogsPolicy",
                                ),
                                iam.PolicyStatement(
                                    actions=["dynamodb:GetItem", "dynamodb:PutItem"],
                                    effect=iam.Effect.ALLOW,
                                    resources=[
                                        self._format_arn(
                                            service="dynamodb",
                                            account=self._account,
                                            resource=f"table/{self.dynamodb_table.ref}",
                                        ),
                                    ],
                                    sid="DynamoDBTable",
                                ),
                            ],
                        ),
                        policy_name="LambdaPolicy",
                    ),
                ],
            )

        update_waiter_lambda = awslambda.CfnFunction(
            scope=self,
            id="UpdateWaiterFunction",
            function_name=f"pcluster-UpdateWaiter-{self._stack_unique_id()}",
            code=awslambda.CfnFunction.CodeProperty(
                s3_bucket=self.bucket.name,
                s3_key=f"{self.bucket.artifact_directory}/custom_resources_code/artifacts.zip",
            ),
            handler="wait_for_update.handler",
            memory_size=128,
            role=update_waiter_lambda_execution_role.attr_arn
            if update_waiter_lambda_execution_role
            else self._format_arn(
                service="iam",
                region="",
                account=self._account,
                resource="role/{0}".format(self.config.iam.roles.custom_lambda_resources),
            ),
            runtime="python3.8",
            timeout=900,
        )

        core.CustomResource(
            self,
            "UpdateWaiterCustomResource",
            service_token=update_waiter_lambda.attr_arn,
            properties={
                "ConfigVersion": self.config.config_version,
                "DynamoDBTable": self.dynamodb_table.ref,
            },
        )

        core.CfnOutput(scope=self, id="UpdateWaiterFunctionArn", value=update_waiter_lambda.attr_arn)

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
            )
        ]
        for device_index in range(1, compute_resource.max_network_interface_count - 1):
            compute_lt_nw_interfaces.append(
                ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                    device_index=device_index,
                    network_card_index=device_index,
                    interface_type="efa" if compute_resource.efa and compute_resource.efa.enabled else None,
                    groups=queue_lt_security_groups,
                    subnet_id=queue.networking.subnet_ids[0],  # FIXME slurm supports a single subnet
                )
            )

        instance_market_options = None
        if queue.compute_type == ComputeType.SPOT:
            instance_market_options = ec2.CfnLaunchTemplate.InstanceMarketOptionsProperty(
                market_type="spot",
                spot_options=ec2.CfnLaunchTemplate.SpotOptionsProperty(
                    spot_instance_type="one-time",
                    instance_interruption_behavior="terminate",
                    max_price=compute_resource.spot_price,
                ),
            )

        ec2.CfnLaunchTemplate(
            scope=self,
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
                placement=queue_placement_group,
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
                            "YumProxy": queue.networking.proxy if queue.networking.proxy else "_none_",
                            "DnfProxy": queue.networking.proxy if queue.networking.proxy else "",
                            "AptProxy": queue.networking.proxy if queue.networking.proxy else "false",
                            "ProxyServer": queue.networking.proxy if queue.networking.proxy else "NONE",
                            "CustomChefCookbook": self.config.custom_chef_cookbook or "NONE",
                            "ParallelClusterVersion": COOKBOOK_PACKAGES_VERSIONS["parallelcluster"],
                            "CookbookVersion": COOKBOOK_PACKAGES_VERSIONS["cookbook"],
                            "ChefVersion": COOKBOOK_PACKAGES_VERSIONS["chef"],
                            "BerkshelfVersion": COOKBOOK_PACKAGES_VERSIONS["berkshelf"],
                            "IamRoleName": str(self.instance_roles[queue.name]["RoleRef"]),
                            "EnableEfa": "efa" if compute_resource.efa and compute_resource.efa.enabled else "NONE",
                            "RAIDOptions": get_shared_storage_options_by_type(
                                self.shared_storage_options, SharedStorageType.RAID
                            ),
                            "DisableHyperThreadingManually": "true"
                            if compute_resource.disable_simultaneous_multithreading_manually
                            else "false",
                            "BaseOS": self.config.image.os,
                            "PreInstallScript": queue_pre_install_action.script if queue_pre_install_action else "NONE",
                            "PreInstallArgs": queue_pre_install_action.args if queue_pre_install_action else "NONE",
                            "PostInstallScript": queue_post_install_action.script
                            if queue_pre_install_action
                            else "NONE",
                            "PostInstallArgs": queue_post_install_action.args if queue_pre_install_action else "NONE",
                            "EFSId": get_shared_storage_ids_by_type(self.shared_storage_ids, SharedStorageType.EFS),
                            "EFSOptions": get_shared_storage_options_by_type(
                                self.shared_storage_options, SharedStorageType.EFS
                            ),  # FIXME
                            "FSXId": get_shared_storage_ids_by_type(self.shared_storage_ids, SharedStorageType.FSX),
                            "FSXOptions": get_shared_storage_options_by_type(
                                self.shared_storage_options, SharedStorageType.FSX
                            ),
                            "Scheduler": self.config.scheduling.scheduler,
                            "EncryptedEphemeral": "true"
                            if queue.storage
                            and queue.storage.ephemeral_volume
                            and queue.storage.ephemeral_volume.encrypted
                            else "NONE",
                            "EphemeralDir": queue.storage.ephemeral_volume.mount_dir
                            if queue.storage and queue.storage.ephemeral_volume
                            else "/scratch",
                            "EbsSharedDirs": get_shared_storage_options_by_type(
                                self.shared_storage_options, SharedStorageType.EBS
                            ),
                            "ClusterDNSDomain": str(self.cluster_hosted_zone.name) if self.cluster_hosted_zone else "",
                            "ClusterHostedZone": str(self.cluster_hosted_zone.attr_id)
                            if self.cluster_hosted_zone
                            else "",
                            "OSUser": OS_MAPPING[self.config.image.os]["user"],
                            "DynamoDBTable": self.dynamodb_table.ref,
                            "IntelHPCPlatform": "true" if self.config.is_intel_hpc_platform_enabled else "false",
                            "CWLoggingEnabled": "true" if self.config.is_cw_logging_enabled else "false",
                            "QueueName": queue.name,
                            "EnableEfaGdr": "compute"
                            if compute_resource.efa and compute_resource.efa.gdr_support
                            else "NONE",
                            "ExtraJson": self.config.extra_chef_attributes,
                        },
                    )
                ),
                monitoring=ec2.CfnLaunchTemplate.MonitoringProperty(enabled=False),
                tag_specifications=[
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="instance",
                        tags=get_default_instance_tags(
                            self.stack_name, self.config, compute_resource, "Compute", self.shared_storage_ids
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
