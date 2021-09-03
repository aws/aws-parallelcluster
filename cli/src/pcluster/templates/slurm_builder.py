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
from collections import namedtuple

from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as awslambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_route53 as route53
from aws_cdk.core import CfnCustomResource, CfnDeletionPolicy, CfnOutput, CfnParameter, CfnTag, Construct, Fn, Stack

from pcluster.aws.aws_api import AWSApi
from pcluster.config.cluster_config import CapacityType, SharedStorageType, SlurmClusterConfig
from pcluster.constants import (
    IAM_ROLE_PATH,
    OS_MAPPING,
    PCLUSTER_CLUSTER_NAME_TAG,
    PCLUSTER_DYNAMODB_PREFIX,
    PCLUSTER_QUEUE_NAME_TAG,
)
from pcluster.models.s3_bucket import S3Bucket
from pcluster.templates.cdk_builder_utils import (
    PclusterLambdaConstruct,
    add_lambda_cfn_role,
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
from pcluster.utils import join_shell_args

CustomDns = namedtuple("CustomDns", ["ref", "name"])


class SlurmConstruct(Construct):
    """Create the resources required when using Slurm as a scheduler."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        stack_name: str,
        cluster_config: SlurmClusterConfig,
        bucket: S3Bucket,
        log_group: logs.CfnLogGroup,
        instance_roles: dict,
        instance_profiles: dict,
        cleanup_lambda_role: iam.CfnRole,
        cleanup_lambda: awslambda.CfnFunction,
        compute_security_groups: dict,
        shared_storage_mappings: dict,
        shared_storage_options: dict,
        shared_storage_attributes: dict,
        **kwargs,
    ):
        super().__init__(scope, id)
        self.stack_scope = scope
        self.stack_name = stack_name
        self.config = cluster_config
        self.bucket = bucket
        self.log_group = log_group
        self.instance_roles = instance_roles
        self.instance_profiles = instance_profiles
        self.cleanup_lambda_role = cleanup_lambda_role
        self.cleanup_lambda = cleanup_lambda
        self.compute_security_groups = compute_security_groups
        self.shared_storage_mappings = shared_storage_mappings
        self.shared_storage_options = shared_storage_options
        self.shared_storage_attributes = shared_storage_attributes

        self._add_parameters()
        self._add_resources()

    # -- Utility methods --------------------------------------------------------------------------------------------- #

    @property
    def _stack_region(self):
        return Stack.of(self).region

    @property
    def _stack_account(self):
        return Stack.of(self).account

    def _stack_unique_id(self):
        return Fn.select(2, Fn.split("/", Stack.of(self).stack_id))

    def _format_arn(self, **kwargs):
        return Stack.of(self).format_arn(**kwargs)

    def _cluster_scoped_iam_path(self):
        """Return a path to be associated IAM roles and instance profiles."""
        return f"{IAM_ROLE_PATH}{self.stack_name}/"

    # -- Parameters -------------------------------------------------------------------------------------------------- #

    def _add_parameters(self):
        if self._condition_custom_cluster_dns():
            domain_name = AWSApi.instance().route53.get_hosted_zone_domain_name(
                self.config.scheduling.settings.dns.hosted_zone_id
            )
        else:
            domain_name = "pcluster."
        cluster_dns_domain = f"{self.stack_name.lower()}.{domain_name}"

        self.cluster_dns_domain = CfnParameter(
            self.stack_scope,
            "ClusterDNSDomain",
            description="DNS Domain of the private hosted zone created within the cluster",
            default=cluster_dns_domain,
        )

    # -- Resources --------------------------------------------------------------------------------------------------- #

    def _add_resources(self):
        # DynamoDB to store cluster states
        self._add_dynamodb_table()

        # Add Slurm Policies to new instances roles
        for node_name, role_info in self.instance_roles.items():
            self._add_policies_to_role(node_name, role_info.get("RoleRef"))

        if self.cleanup_lambda_role:
            self._add_policies_to_cleanup_resources_lambda_role()

        self._add_slurm_compute_fleet()

    def _add_policies_to_role(self, node_name, role):
        suffix = create_hash_suffix(node_name)

        if node_name == "HeadNode":
            policy_statements = [
                {
                    "sid": "DynamoDBTable",
                    "actions": [
                        "dynamodb:PutItem",
                        "dynamodb:BatchWriteItem",
                        "dynamodb:GetItem",
                        "dynamodb:DeleteItem",
                        "dynamodb:DescribeTable",
                    ],
                    "effect": iam.Effect.ALLOW,
                    "resources": [
                        self._format_arn(
                            service="dynamodb", resource=f"table/{PCLUSTER_DYNAMODB_PREFIX}{self.stack_name}"
                        )
                    ],
                },
                {
                    "sid": "EC2Terminate",
                    "effect": iam.Effect.ALLOW,
                    "actions": ["ec2:TerminateInstances"],
                    "resources": ["*"],
                    "conditions": {"StringEquals": {f"ec2:ResourceTag/{PCLUSTER_CLUSTER_NAME_TAG}": self.stack_name}},
                },
                {
                    "sid": "EC2RunInstances",
                    "effect": iam.Effect.ALLOW,
                    "actions": ["ec2:RunInstances"],
                    "resources": [
                        self._format_arn(service="ec2", resource=f"subnet/{subnet_id}")
                        for subnet_id in self.config.compute_subnet_ids
                    ]
                    + [
                        self._format_arn(service="ec2", resource="network-interface/*"),
                        self._format_arn(service="ec2", resource="instance/*"),
                        self._format_arn(service="ec2", resource="volume/*"),
                        self._format_arn(service="ec2", resource=f"key-pair/{self.config.head_node.ssh.key_name}"),
                        self._format_arn(service="ec2", resource="security-group/*"),
                        self._format_arn(service="ec2", resource="launch-template/*"),
                        self._format_arn(service="ec2", resource="placement-group/*"),
                    ]
                    + [
                        self._format_arn(service="ec2", resource=f"image/{queue_ami}", account="")
                        for _, queue_ami in self.config.image_dict.items()
                    ],
                },
                {
                    "sid": "PassRole",
                    "actions": ["iam:PassRole"],
                    "effect": iam.Effect.ALLOW,
                    "resources": self._generate_head_node_pass_role_resources(),
                },
                {
                    "sid": "EC2",
                    "effect": iam.Effect.ALLOW,
                    "actions": [
                        "ec2:DescribeInstances",
                        "ec2:DescribeInstanceStatus",
                        "ec2:CreateTags",
                        "ec2:DescribeVolumes",
                        "ec2:AttachVolume",
                    ],
                    "resources": ["*"],
                },
                {
                    "sid": "ResourcesS3Bucket",
                    "effect": iam.Effect.ALLOW,
                    "actions": ["s3:*"],
                    "resources": [
                        self._format_arn(service="s3", resource=self.bucket.name, region="", account=""),
                        self._format_arn(
                            service="s3",
                            resource=f"{self.bucket.name}/{self.bucket.artifact_directory}/*",
                            region="",
                            account="",
                        ),
                    ],
                },
                {
                    "sid": "Cloudformation",
                    "actions": [
                        "cloudformation:DescribeStackResource",
                        "cloudformation:SignalResource",
                    ],
                    "effect": iam.Effect.ALLOW,
                    "resources": [
                        self._format_arn(service="cloudformation", resource=f"stack/{self.stack_name}/*"),
                        # ToDo: This resource is for substack. Check if this is necessary for pcluster3
                        self._format_arn(service="cloudformation", resource=f"stack/{self.stack_name}-*/*"),
                    ],
                },
                {
                    "sid": "DcvLicense",
                    "actions": ["s3:GetObject"],
                    "effect": iam.Effect.ALLOW,
                    "resources": [
                        self._format_arn(
                            service="s3",
                            resource="dcv-license.{0}/*".format(self._stack_region),
                            region="",
                            account="",
                        )
                    ],
                },
            ]
            policy_name = "parallelcluster-slurm-head-node"
        else:
            policy_statements = [
                {
                    "sid": "DynamoDBTableQuery",
                    "effect": iam.Effect.ALLOW,
                    "actions": ["dynamodb:Query"],
                    "resources": [
                        self._format_arn(
                            service="dynamodb", resource=f"table/{PCLUSTER_DYNAMODB_PREFIX}{self.stack_name}"
                        ),
                        self._format_arn(
                            service="dynamodb",
                            resource=f"table/{PCLUSTER_DYNAMODB_PREFIX}{self.stack_name}/index/*",
                        ),
                    ],
                },
            ]
            policy_name = "parallelcluster-slurm-compute"
        iam.CfnPolicy(
            self.stack_scope,
            f"SlurmPolicies{suffix}",
            policy_name=policy_name,
            policy_document=iam.PolicyDocument(
                statements=[iam.PolicyStatement(**statement) for statement in policy_statements]
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
                conditions={"StringEquals": {f"ec2:ResourceTag/{PCLUSTER_CLUSTER_NAME_TAG}": self.stack_name}},
                sid="FleetTerminatePolicy",
            ),
        )

    def _add_slurm_compute_fleet(self):

        self.cluster_hosted_zone = None
        if not self._condition_disable_cluster_dns():
            self.cluster_hosted_zone = self._add_private_hosted_zone()

        self.terminate_compute_fleet_custom_resource = CfnCustomResource(
            self.stack_scope,
            "TerminateComputeFleetCustomResource",
            service_token=self.cleanup_lambda.attr_arn,
        )
        self.terminate_compute_fleet_custom_resource.add_property_override("StackName", self.stack_name)
        self.terminate_compute_fleet_custom_resource.add_property_override("Action", "TERMINATE_EC2_INSTANCES")
        if not self._condition_disable_cluster_dns():
            self.terminate_compute_fleet_custom_resource.add_depends_on(self.cleanup_route53_custom_resource)
        for security_group in self.compute_security_groups.values():
            # Control the order of resource deletion.
            # Security groups can be deleted only after the compute nodes are terminated.
            self.terminate_compute_fleet_custom_resource.add_depends_on(security_group)
        # TODO: add depends_on resources from CloudWatchLogsSubstack and ComputeFleetHitSubstack?
        # terminate_compute_fleet_custom_resource.add_depends_on()

        for queue in self.config.scheduling.queues:
            queue_lt_security_groups = get_queue_security_groups_full(self.compute_security_groups, queue)

            queue_placement_group = None
            if queue.networking.placement_group and queue.networking.placement_group.enabled:
                if queue.networking.placement_group.id:
                    queue_placement_group = queue.networking.placement_group.id
                else:
                    # Create Placement Group
                    queue_placement_group = ec2.CfnPlacementGroup(
                        self.stack_scope, f"PlacementGroup{create_hash_suffix(queue.name)}", strategy="cluster"
                    )
                    # Control the order of resource deletion.
                    # Placement group can be deleted only after the compute nodes are terminated.
                    self.terminate_compute_fleet_custom_resource.add_depends_on(queue_placement_group)
                    queue_placement_group = queue_placement_group.ref

            queue_pre_install_action, queue_post_install_action = (None, None)
            if queue.custom_actions:
                queue_pre_install_action = queue.custom_actions.on_node_start
                queue_post_install_action = queue.custom_actions.on_node_configured

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

    def _add_dynamodb_table(self):
        table = dynamodb.CfnTable(
            self.stack_scope,
            "DynamoDBTable",
            table_name=PCLUSTER_DYNAMODB_PREFIX + self.stack_name,
            attribute_definitions=[
                dynamodb.CfnTable.AttributeDefinitionProperty(attribute_name="Id", attribute_type="S"),
                dynamodb.CfnTable.AttributeDefinitionProperty(attribute_name="InstanceId", attribute_type="S"),
            ],
            key_schema=[dynamodb.CfnTable.KeySchemaProperty(attribute_name="Id", key_type="HASH")],
            global_secondary_indexes=[
                dynamodb.CfnTable.GlobalSecondaryIndexProperty(
                    index_name="InstanceId",
                    key_schema=[dynamodb.CfnTable.KeySchemaProperty(attribute_name="InstanceId", key_type="HASH")],
                    projection=dynamodb.CfnTable.ProjectionProperty(projection_type="ALL"),
                )
            ],
            billing_mode="PAY_PER_REQUEST",
        )
        table.cfn_options.update_replace_policy = CfnDeletionPolicy.RETAIN
        table.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE
        self.dynamodb_table = table

    def _add_private_hosted_zone(self):
        if self._condition_custom_cluster_dns():
            hosted_zone_id = self.config.scheduling.settings.dns.hosted_zone_id
            cluster_hosted_zone = CustomDns(ref=hosted_zone_id, name=self.cluster_dns_domain.value_as_string)
        else:
            cluster_hosted_zone = route53.CfnHostedZone(
                self.stack_scope,
                "Route53HostedZone",
                name=self.cluster_dns_domain.value_as_string,
                vpcs=[route53.CfnHostedZone.VPCProperty(vpc_id=self.config.vpc_id, vpc_region=self._stack_region)],
            )

        # If Headnode InstanceRole is created by ParallelCluster, add Route53 policy for InstanceRole
        head_node_role_info = self.instance_roles.get("HeadNode")
        if head_node_role_info:
            iam.CfnPolicy(
                self.stack_scope,
                "ParallelClusterSlurmRoute53Policies",
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
            else self.config.iam.roles.lambda_functions_role,
            handler_func="cleanup_resources",
        ).lambda_func

        self.cleanup_route53_custom_resource = CfnCustomResource(
            self.stack_scope,
            "CleanupRoute53CustomResource",
            service_token=cleanup_route53_lambda.attr_arn,
        )
        self.cleanup_route53_custom_resource.add_property_override("ClusterHostedZone", cluster_hosted_zone.ref)
        self.cleanup_route53_custom_resource.add_property_override("Action", "DELETE_DNS_RECORDS")
        self.cleanup_route53_custom_resource.add_property_override("ClusterDNSDomain", cluster_hosted_zone.name)

        CfnOutput(
            self.stack_scope,
            "ClusterHostedZone",
            description="Id of the private hosted zone created within the cluster",
            value=cluster_hosted_zone.ref,
        )

        return cluster_hosted_zone

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
                    max_price=None if compute_resource.spot_price is None else str(compute_resource.spot_price),
                ),
            )

        ec2.CfnLaunchTemplate(
            self.stack_scope,
            f"ComputeServerLaunchTemplate{create_hash_suffix(queue.name + instance_type)}",
            launch_template_name=f"{self.stack_name}-{queue.name}-{instance_type}",
            launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
                instance_type=instance_type,
                cpu_options=ec2.CfnLaunchTemplate.CpuOptionsProperty(
                    core_count=compute_resource.vcpus, threads_per_core=1
                )
                if compute_resource.pass_cpu_options_in_launch_template
                else None,
                block_device_mappings=get_block_device_mappings(
                    queue.compute_settings.local_storage, self.config.image.os
                ),
                # key_name=,
                network_interfaces=compute_lt_nw_interfaces,
                placement=ec2.CfnLaunchTemplate.PlacementProperty(group_name=queue_placement_group),
                image_id=self.config.image_dict[queue.name],
                ebs_optimized=compute_resource.is_ebs_optimized,
                iam_instance_profile=ec2.CfnLaunchTemplate.IamInstanceProfileProperty(
                    name=self.instance_profiles[queue.name]
                ),
                instance_market_options=instance_market_options,
                user_data=Fn.base64(
                    Fn.sub(
                        get_user_data_content("../resources/compute_node/user_data.sh"),
                        {
                            **{
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
                                "PreInstallArgs": join_shell_args(queue_pre_install_action.args)
                                if queue_pre_install_action and queue_pre_install_action.args
                                else "NONE",
                                "PostInstallScript": queue_post_install_action.script
                                if queue_post_install_action
                                else "NONE",
                                "PostInstallArgs": join_shell_args(queue_post_install_action.args)
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
                                "FSXMountName": self.shared_storage_attributes[SharedStorageType.FSX].get(
                                    "MountName", ""
                                ),
                                "FSXDNSName": self.shared_storage_attributes[SharedStorageType.FSX].get("DNSName", ""),
                                "FSXOptions": get_shared_storage_options_by_type(
                                    self.shared_storage_options, SharedStorageType.FSX
                                ),
                                "Scheduler": self.config.scheduling.scheduler,
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
                                "CustomNodePackage": self.config.custom_node_package or "",
                                "CustomAwsBatchCliPackage": self.config.custom_aws_batch_cli_package or "",
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
                        + [CfnTag(key=PCLUSTER_QUEUE_NAME_TAG, value=queue.name)]
                        + get_custom_tags(self.config),
                    ),
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="volume",
                        tags=get_default_volume_tags(self.stack_name, "Compute")
                        + [CfnTag(key=PCLUSTER_QUEUE_NAME_TAG, value=queue.name)]
                        + get_custom_tags(self.config),
                    ),
                ],
            ),
        )

    def _generate_head_node_pass_role_resources(self):
        """Return a unique list of ARNs that the head node should be able to use when calling PassRole."""
        default_pass_role_resource = self._format_arn(
            service="iam",
            region="",
            resource=f"role{self._cluster_scoped_iam_path()}*",
        )

        # If there are any queues where a custom instance role was specified,
        # enable the head node to pass permissions to those roles.
        custom_queue_role_arns = {
            arn for queue in self.config.scheduling.queues for arn in queue.iam.instance_role_arns
        }
        if custom_queue_role_arns:
            pass_role_resources = custom_queue_role_arns

            # Include the default IAM role path for the queues that
            # aren't using a custom instance role.
            queues_without_custom_roles = [
                queue for queue in self.config.scheduling.queues if not queue.iam.instance_role_arns
            ]
            if any(queues_without_custom_roles):
                pass_role_resources.add(default_pass_role_resource)
        else:
            pass_role_resources = {default_pass_role_resource}
        return list(pass_role_resources)

    # -- Conditions -------------------------------------------------------------------------------------------------- #

    def _condition_disable_cluster_dns(self):
        return (
            self.config.scheduling.settings
            and self.config.scheduling.settings.dns
            and self.config.scheduling.settings.dns.disable_managed_dns
        )

    def _condition_custom_cluster_dns(self):
        return (
            self.config.scheduling.settings
            and self.config.scheduling.settings.dns
            and self.config.scheduling.settings.dns.hosted_zone_id
        )
