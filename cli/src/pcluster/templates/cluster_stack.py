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

#
# This module contains all the classes required to convert a Cluster into a CFN template by using CDK.
#
import json
from collections import namedtuple
from datetime import datetime
from typing import Union

from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_efs as efs
from aws_cdk import aws_fsx as fsx
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import core

from common.aws.aws_api import AWSApi
from pcluster.constants import OS_MAPPING
from pcluster.models.cluster_config import (
    BaseQueue,
    ClusterBucket,
    CustomActionEvent,
    HeadNode,
    SharedEbs,
    SharedEfs,
    SharedFsx,
    SharedStorageType,
    SlurmClusterConfig,
)
from pcluster.templates.awsbatch_builder import AwsbatchConstruct
from pcluster.templates.cdk_builder_utils import (
    PclusterLambdaConstruct,
    add_lambda_cfn_role,
    cluster_name,
    create_hash_suffix,
    get_block_device_mappings,
    get_cloud_watch_logs_policy_statement,
    get_cloud_watch_logs_retention_days,
    get_common_user_data_env,
    get_custom_tags,
    get_default_instance_tags,
    get_default_volume_tags,
    get_shared_storage_ids_by_type,
    get_shared_storage_options_by_type,
    get_user_data_content,
)
from pcluster.templates.cw_dashboard_builder import CWDashboardConstruct
from pcluster.templates.slurm_builder import SlurmConstruct

# pylint: disable=too-many-lines

StorageInfo = namedtuple("StorageInfo", ["id", "config"])


class ClusterCdkStack(core.Stack):
    """Create the CloudFormation stack template for the Cluster."""

    def __init__(
        self,
        scope: core.Construct,
        construct_id: str,
        stack_name: str,
        cluster_config: SlurmClusterConfig,
        bucket: ClusterBucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self._stack_name = stack_name
        self.config = cluster_config
        self.bucket = bucket

        self.instance_roles = {}
        self.instance_profiles = {}
        self.compute_security_groups = {}
        self.shared_storage_mappings = {storage_type: [] for storage_type in SharedStorageType}
        self.shared_storage_options = {storage_type: "" for storage_type in SharedStorageType}

        self._add_resources()
        self._add_outputs()

    # -- Utility methods --------------------------------------------------------------------------------------------- #

    def _stack_unique_id(self):
        return core.Fn.select(2, core.Fn.split("/", self.stack_id))

    def _get_head_node_security_groups(self):
        """Return the security groups to be used for the head node, created by us OR provided by the user."""
        return self.config.head_node.networking.security_groups or [self._head_security_group.ref]

    def _get_head_node_security_groups_full(self):
        """Return full security groups to be used for the head node, default plus additional ones."""
        head_node_group_set = self._get_head_node_security_groups()
        # Additional security groups
        if self.config.head_node.networking.additional_security_groups:
            head_node_group_set.extend(self.config.head_node.networking.additional_security_groups)

        return head_node_group_set

    def _get_compute_security_groups(self):
        """Return list of security groups to be used for the compute, created by us AND provided by the user."""
        compute_group_set = self.config.compute_security_groups
        if self._compute_security_group:
            compute_group_set.append(self._compute_security_group.ref)

        return compute_group_set

    # -- Resources --------------------------------------------------------------------------------------------------- #

    def _add_resources(self):
        # Cloud Watch Logs
        if self.config.is_cw_logging_enabled:
            self.log_group = self._add_cluster_log_group()

        # Head Node EC2 Iam Role
        self._add_role_and_policies(self.config.head_node, "HeadNode")

        # Compute Nodes EC2 Iam Roles
        for queue in self.config.scheduling.queues:
            self._add_role_and_policies(queue, queue.name)

        # Managed security groups
        self._head_security_group, self._compute_security_group = self._add_security_groups()

        # Head Node ENI
        self._head_eni = self._add_head_eni()

        # Additional Cfn Stack
        if self.config.additional_resources:
            core.CfnStack(scope=self, id="AdditionalCfnStack", template_url=self.config.additional_resources)

        # AWSBatchStack
        # TODO: inline resources

        # Cleanup Resources Lambda Function
        cleanup_lambda_role, cleanup_lambda = self._add_cleanup_resources_lambda()

        # DynamoDB to store cluster states
        # ToDo: evaluate other approaches to store cluster states
        self.dynamodb_table = self._add_dynamodb_table()

        if self.config.shared_storage:
            for storage in self.config.shared_storage:
                self._add_shared_storage(storage)

        # Compute Fleet and scheduler related resources
        self.scheduler_resources = None
        if self._condition_is_slurm():
            self.scheduler_resources = SlurmConstruct(
                scope=self,
                id="Slurm",
                stack_name=self._stack_name,
                cluster_config=self.config,
                bucket=self.bucket,
                dynamodb_table=self.dynamodb_table,
                log_group=self.log_group,
                instance_roles=self.instance_roles,
                instance_profiles=self.instance_profiles,
                cleanup_lambda_role=cleanup_lambda_role,  # None if provided by the user
                cleanup_lambda=cleanup_lambda,
                compute_security_groups=self.compute_security_groups,  # Empty dict if provided by the user
                shared_storage_mappings=self.shared_storage_mappings,
                shared_storage_options=self.shared_storage_options,
            )

        # Head Node
        self.head_node_instance = self._add_head_node()

        # AWS Batch related resources
        if self.config.scheduling.scheduler == "awsbatch":
            self.scheduler_resources = AwsbatchConstruct(
                scope=self,
                id="Awsbatch",
                stack_name=self._stack_name,
                cluster_config=self.config,
                bucket=self.bucket,
                create_lambda_roles=self._condition_create_lambda_iam_role(),
                compute_security_groups=self.compute_security_groups,  # Empty dict if provided by the user
                shared_storage_mappings=self.shared_storage_mappings,
                shared_storage_options=self.shared_storage_options,
                head_node_instance=self.head_node_instance,
            )

        # CloudWatchDashboardSubstack
        if self.config.is_cw_dashboard_enabled:
            self.cloudwatch_dashboard = CWDashboardConstruct(
                scope=self,
                id="PclusterDashboard",
                stack_name=self.stack_name,
                cluster_config=self.config,
                head_node_instance=self.head_node_instance,
                shared_storage_mappings=self.shared_storage_mappings,
                cw_log_group_name=self.log_group.log_group_name if self.config.is_cw_logging_enabled else None,
            )

    def _add_cluster_log_group(self):
        timestamp = f"{datetime.now().strftime('%Y%m%d%H%M')}"
        log_group = logs.CfnLogGroup(
            scope=self,
            id="CloudWatchLogGroup",
            log_group_name=f"/aws/parallelcluster/{cluster_name(self.stack_name)}-{timestamp}",
            retention_in_days=get_cloud_watch_logs_retention_days(self.config),
        )
        return log_group

    def _add_role_and_policies(self, node: Union[HeadNode, BaseQueue], name: str):
        """Create role and policies for the given node/queue."""
        suffix = create_hash_suffix(name)
        if node.instance_role:
            node_role_ref = node.instance_role
            is_new = False
        else:
            node_role_ref = self._add_node_role(node, f"Role{suffix}")
            is_new = True

            # ParallelCluster Policies
            self._add_pcluster_policies_to_role(node_role_ref, f"ParallelClusterPolicies{suffix}")

            # S3 Access Policies
            if self._condition_create_s3_access_policies(node):
                self._add_s3_access_policies_to_role(node, node_role_ref, f"S3AccessPolicies{suffix}")

        self.instance_roles[name] = {"RoleRef": node_role_ref, "IsNew": is_new}

        # Head node Instance Profile
        self.instance_profiles[name] = self._add_instance_profile(node_role_ref, f"InstanceProfile{suffix}")

    def _add_cleanup_resources_lambda(self):
        """Create Lambda cleanup resources function and its role."""
        cleanup_resources_lambda_role = None
        if self._condition_create_lambda_iam_role():
            s3_policy_actions = ["s3:DeleteObject", "s3:DeleteObjectVersion", "s3:ListBucket", "s3:ListBucketVersions"]
            if self.bucket.remove_on_deletion:
                s3_policy_actions.append("s3:DeleteBucket")

            cleanup_resources_lambda_role = add_lambda_cfn_role(
                scope=self,
                function_id="CleanupResources",
                statements=[
                    iam.PolicyStatement(
                        actions=s3_policy_actions,
                        effect=iam.Effect.ALLOW,
                        resources=[
                            self.format_arn(service="s3", resource=self.bucket.name, region="", account=""),
                            self.format_arn(
                                service="s3",
                                resource=f"{self.bucket.name}/{self.bucket.artifact_directory}/*",
                                region="",
                                account="",
                            ),
                        ],
                        sid="S3BucketPolicy",
                    ),
                    get_cloud_watch_logs_policy_statement(
                        resource=self.format_arn(service="logs", account="*", region="*", resource="*")
                    ),
                ],
            )

        cleanup_resources_lambda = PclusterLambdaConstruct(
            scope=self,
            id="CleanupResourcesFunctionConstruct",
            function_id="CleanupResources",
            bucket=self.bucket,
            config=self.config,
            execution_role=cleanup_resources_lambda_role.attr_arn
            if cleanup_resources_lambda_role
            else self.format_arn(
                service="iam",
                region="",
                account=self.account,
                resource="role/{0}".format(self.config.iam.roles.custom_lambda_resources),
            ),
            handler_func="cleanup_resources",
        ).lambda_func

        core.CustomResource(
            scope=self,
            id="CleanupResourcesS3BucketCustomResource",
            service_token=cleanup_resources_lambda.attr_arn,
            properties={
                "ResourcesS3Bucket": self.bucket.name,
                "ArtifactS3RootDirectory": self.bucket.artifact_directory,
                "RemoveBucketOnDeletion": self.bucket.remove_on_deletion,
                "Action": "DELETE_S3_ARTIFACTS",
            },
        )

        return cleanup_resources_lambda_role, cleanup_resources_lambda

    def _add_head_eni(self):
        """Create Head Node Elastic Network Interface."""
        head_eni_group_set = self._get_head_node_security_groups_full()

        head_eni = ec2.CfnNetworkInterface(
            scope=self,
            id="HeadNodeENI",
            description="AWS ParallelCluster head node interface",
            subnet_id=self.config.head_node.networking.subnet_id,
            source_dest_check=False,
            group_set=head_eni_group_set,
        )

        # Create and associate EIP to Head Node
        if self.config.head_node.networking.elastic_ip:
            head_eip = ec2.CfnEIP(scope=self, id="HeadNodeEIP", domain="vpc")

            ec2.CfnEIPAssociation(
                scope=self,
                id="AssociateEIP",
                allocation_id=head_eip.attr_allocation_id,
                network_interface_id=head_eni.ref,
            )

        return head_eni

    def _add_security_groups(self):
        """Associate security group to Head node and queues."""
        # Head Node Security Group
        head_security_group = None
        if not self.config.head_node.networking.security_groups:
            head_security_group = self._add_head_security_group()

        # Compute Security Groups
        compute_security_group = None
        for queue in self.config.scheduling.queues:
            if not queue.networking.security_groups:
                if not compute_security_group:
                    # Create a new security group
                    compute_security_group = self._add_compute_security_group()
                # Associate created security group to the queue
                self.compute_security_groups[queue.name] = compute_security_group.ref

        if head_security_group and compute_security_group:
            # Access to head node from compute nodes
            ec2.CfnSecurityGroupIngress(
                scope=self,
                id="HeadNodeSecurityGroupComputeIngress",
                ip_protocol="-1",
                from_port=0,
                to_port=65535,
                source_security_group_id=compute_security_group.ref,
                group_id=head_security_group.ref,
            )

            # Access to compute nodes from head node
            ec2.CfnSecurityGroupIngress(
                scope=self,
                id="ComputeSecurityGroupHeadNodeIngress",
                ip_protocol="-1",
                from_port=0,
                to_port=65535,
                source_security_group_id=head_security_group.ref,
                group_id=compute_security_group.ref,
            )

        return head_security_group, compute_security_group

    def _add_compute_security_group(self):
        compute_security_group = ec2.CfnSecurityGroup(
            scope=self,
            id="ComputeSecurityGroup",
            group_description="Allow access to compute nodes",
            vpc_id=self.config.vpc_id,
        )

        # ComputeSecurityGroupEgress
        # Access to other compute nodes from compute nodes
        compute_security_group_egress = ec2.CfnSecurityGroupEgress(
            scope=self,
            id="ComputeSecurityGroupEgress",
            ip_protocol="-1",
            from_port=0,
            to_port=65535,
            destination_security_group_id=compute_security_group.ref,
            group_id=compute_security_group.ref,
        )

        # ComputeSecurityGroupNormalEgress
        # Internet access from compute nodes
        ec2.CfnSecurityGroupEgress(
            scope=self,
            id="ComputeSecurityGroupNormalEgress",
            ip_protocol="-1",
            from_port=0,
            to_port=65535,
            cidr_ip="0.0.0.0/0",
            group_id=compute_security_group.ref,
        ).add_depends_on(compute_security_group_egress)

        # ComputeSecurityGroupIngress
        # Access to compute nodes from other compute nodes
        ec2.CfnSecurityGroupIngress(
            scope=self,
            id="ComputeSecurityGroupIngress",
            ip_protocol="-1",
            from_port=0,
            to_port=65535,
            source_security_group_id=compute_security_group.ref,
            group_id=compute_security_group.ref,
        )

        return compute_security_group

    def _add_s3_access_policies_to_role(self, node: Union[HeadNode, BaseQueue], role_ref: str, name: str):
        """Attach S3 policies to given role."""
        read_only_s3_resources = [
            self.format_arn(service="s3", resource=s3_access.bucket_name + "*", region="", account="")
            for s3_access in node.iam.s3_access
            if not s3_access.enable_write_access
        ]
        read_write_s3_resources = [
            self.format_arn(service="s3", resource=s3_access.bucket_name + "/*", region="", account="")
            for s3_access in node.iam.s3_access
            if s3_access.enable_write_access
        ]

        s3_access_policy = iam.CfnPolicy(
            scope=self,
            id=name,
            policy_document=iam.PolicyDocument(statements=[]),
            roles=[role_ref],
            policy_name="S3Access",
        )

        if read_only_s3_resources:
            s3_access_policy.policy_document.add_statements(
                iam.PolicyStatement(
                    sid="S3Read",
                    effect=iam.Effect.ALLOW,
                    actions=["s3:Get*", "s3:List*"],
                    resources=read_only_s3_resources,
                )
            )

        if read_write_s3_resources:
            s3_access_policy.policy_document.add_statements(
                iam.PolicyStatement(
                    sid="S3ReadWrite", effect=iam.Effect.ALLOW, actions=["s3:*"], resources=read_write_s3_resources
                )
            )

    def _add_instance_profile(self, role_ref: str, name: str):
        return iam.CfnInstanceProfile(scope=self, id=name, roles=[role_ref], path="/").ref

    def _add_node_role(self, node: Union[HeadNode, BaseQueue], name: str):
        additional_iam_policies = node.iam.additional_iam_policy_arns
        if self.config.monitoring.logs.cloud_watch.enabled:
            cloud_watch_policy_arn = self.format_arn(
                service="iam", region="", account="aws", resource="policy/CloudWatchAgentServerPolicy"
            )
            if cloud_watch_policy_arn not in additional_iam_policies:
                additional_iam_policies.append(cloud_watch_policy_arn)
        # ToDo check if AWSBatchFullAccess needs to be added
        return iam.CfnRole(
            scope=self,
            id=name,
            managed_policy_arns=additional_iam_policies,
            assume_role_policy_document=iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        effect=iam.Effect.ALLOW,
                        principals=[
                            iam.ServicePrincipal(
                                service="ec2.{0}".format(self.url_suffix),
                            )
                        ],
                        actions=["sts:AssumeRole"],
                    )
                ]
            ),
            path="/",
        ).ref

    def _add_pcluster_policies_to_role(self, role_ref: str, name: str):
        iam.CfnPolicy(
            scope=self,
            id=name,
            policy_name="parallelcluster",
            policy_document=iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        sid="Ec2",
                        actions=[
                            "ec2:DescribeVolumes",
                            "ec2:AttachVolume",
                            "ec2:DescribeInstanceAttribute",
                            "ec2:DescribeInstanceStatus",
                            "ec2:DescribeInstances",
                            "ec2:DescribeInstanceTypes",
                        ],
                        effect=iam.Effect.ALLOW,
                        resources=["*"],
                    ),
                    iam.PolicyStatement(
                        sid="DynamoDBList", actions=["dynamodb:ListTables"], effect=iam.Effect.ALLOW, resources=["*"]
                    ),
                    iam.PolicyStatement(
                        sid="SQSQueue",
                        actions=[
                            "sqs:SendMessage",
                            "sqs:ReceiveMessage",
                            "sqs:ChangeMessageVisibility",
                            "sqs:DeleteMessage",
                            "sqs:GetQueueUrl",
                        ],
                        effect=iam.Effect.ALLOW,
                        resources=[self.format_arn(service="sqs", resource=self._stack_name)],
                    ),
                    iam.PolicyStatement(
                        sid="Cloudformation",
                        actions=[
                            "cloudformation:DescribeStacks",
                            "cloudformation:DescribeStackResource",
                            "cloudformation:SignalResource",
                        ],
                        effect=iam.Effect.ALLOW,
                        resources=[self.format_arn(service="cloudformation", resource="stack/parallelcluster-*/*")],
                    ),
                    iam.PolicyStatement(
                        sid="DynamoDBTable",
                        actions=[
                            "dynamodb:PutItem",
                            "dynamodb:BatchWriteItem",
                            "dynamodb:GetItem",
                            "dynamodb:DeleteItem",
                            "dynamodb:DescribeTable",
                        ],
                        effect=iam.Effect.ALLOW,
                        resources=[self.format_arn(service="dynamodb", resource=f"table/{self._stack_name}")],
                    ),
                    iam.PolicyStatement(
                        sid="S3GetObj",
                        actions=["s3:GetObject"],
                        effect=iam.Effect.ALLOW,
                        resources=[
                            self.format_arn(
                                service="s3",
                                resource="{0}-aws-parallelcluster/*".format(self.region),
                                region="",
                                account="",
                            )
                        ],
                    ),
                    iam.PolicyStatement(
                        sid="S3PutObj",
                        actions=["s3:PutObject"],
                        effect=iam.Effect.ALLOW,
                        resources=[
                            self.format_arn(
                                service="s3",
                                resource=f"{self.bucket.name}/{self.bucket.artifact_directory}/batch/",
                                region="",
                                account="",
                            )
                        ],
                    ),
                    iam.PolicyStatement(
                        sid="FSx", actions=["fsx:DescribeFileSystems"], effect=iam.Effect.ALLOW, resources=["*"]
                    ),
                    iam.PolicyStatement(
                        sid="BatchJobPassRole",
                        actions=["iam:PassRole"],
                        effect=iam.Effect.ALLOW,
                        resources=[self.format_arn(service="iam", region="", resource="role/parallelcluster-*")],
                    ),
                    iam.PolicyStatement(
                        sid="DcvLicense",
                        actions=["s3:GetObject"],
                        effect=iam.Effect.ALLOW,
                        resources=[
                            self.format_arn(
                                service="s3",
                                resource="dcv-license.{0}/*".format(self.region),
                                region="",
                                account="",
                            )
                        ],
                    ),
                ]
            ),
            roles=[role_ref],
        )

    def _add_head_security_group(self):
        head_security_group_ingress = [
            # SSH access
            ec2.CfnSecurityGroup.IngressProperty(
                ip_protocol="tcp",
                from_port=22,
                to_port=22,
                cidr_ip=self.config.head_node.ssh.allowed_ips,
            ),
        ]

        if self.config.is_dcv_enabled:
            head_security_group_ingress.append(
                # DCV access
                ec2.CfnSecurityGroup.IngressProperty(
                    ip_protocol="tcp",
                    from_port=self.config.head_node.dcv.port,
                    to_port=self.config.head_node.dcv.port,
                    cidr_ip=self.config.head_node.dcv.allowed_ips,
                )
            )
        return ec2.CfnSecurityGroup(
            scope=self,
            id="HeadNodeSecurityGroup",
            group_description="Enable access to the head node",
            vpc_id=self.config.vpc_id,
            security_group_ingress=head_security_group_ingress,
        )

    def _add_shared_storage(self, storage):
        """Add specific Cfn Resources to map the shared storage and store the output filesystem id."""
        storage_ids_list = self.shared_storage_mappings[storage.shared_storage_type]
        cfn_resource_id = "{0}{1}".format(storage.shared_storage_type.name, len(storage_ids_list))
        if storage.shared_storage_type == SharedStorageType.FSX:
            storage_ids_list.append(StorageInfo(self._add_fsx_storage(cfn_resource_id, storage), storage))
        elif storage.shared_storage_type == SharedStorageType.EBS:
            storage_ids_list.append(StorageInfo(self._add_ebs_volume(cfn_resource_id, storage), storage))
        elif storage.shared_storage_type == SharedStorageType.EFS:
            storage_ids_list.append(StorageInfo(self._add_efs_storage(cfn_resource_id, storage), storage))
        elif storage.shared_storage_type == SharedStorageType.RAID:
            storage_ids_list.extend(self._add_raid_volume(cfn_resource_id, storage))

    def _add_fsx_storage(self, id: str, shared_fsx: SharedFsx):
        """Add specific Cfn Resources to map the FSX storage."""
        fsx_id = shared_fsx.file_system_id

        if not fsx_id and shared_fsx.mount_dir:
            fsx_resource = fsx.CfnFileSystem(
                scope=self,
                storage_capacity=shared_fsx.storage_capacity,
                lustre_configuration=fsx.CfnFileSystem.LustreConfigurationProperty(
                    deployment_type=shared_fsx.deployment_type,
                    imported_file_chunk_size=shared_fsx.imported_file_chunk_size,
                    export_path=shared_fsx.export_path,
                    import_path=shared_fsx.import_path,
                    weekly_maintenance_start_time=shared_fsx.weekly_maintenance_start_time,
                    automatic_backup_retention_days=shared_fsx.automatic_backup_retention_days,
                    copy_tags_to_backups=shared_fsx.copy_tags_to_backups,
                    daily_automatic_backup_start_time=shared_fsx.daily_automatic_backup_start_time,
                    per_unit_storage_throughput=shared_fsx.per_unit_storage_throughput,
                    auto_import_policy=shared_fsx.auto_import_policy,
                    drive_cache_type=shared_fsx.drive_cache_type,
                ),
                backup_id=shared_fsx.backup_id,
                kms_key_id=shared_fsx.kms_key_id,
                id=id,
                file_system_type="LUSTRE",
                storage_type=shared_fsx.drive_cache_type,
                subnet_ids=self.config.compute_subnet_ids,
                security_group_ids=self._get_compute_security_groups(),
            )
            fsx_id = fsx_resource.ref

        # [shared_dir,fsx_fs_id,storage_capacity,fsx_kms_key_id,imported_file_chunk_size,
        # export_path,import_path,weekly_maintenance_start_time,deployment_type,
        # per_unit_storage_throughput,daily_automatic_backup_start_time,
        # automatic_backup_retention_days,copy_tags_to_backups,fsx_backup_id,
        # auto_import_policy,storage_type,drive_cache_type]",
        self.shared_storage_options[shared_fsx.shared_storage_type] = ",".join(
            str(item)
            for item in [
                shared_fsx.mount_dir,
                fsx_id,
                shared_fsx.storage_capacity or "NONE",
                shared_fsx.kms_key_id or "NONE",
                shared_fsx.imported_file_chunk_size or "NONE",
                shared_fsx.export_path or "NONE",
                shared_fsx.import_path or "NONE",
                shared_fsx.weekly_maintenance_start_time or "NONE",
                shared_fsx.deployment_type or "NONE",
                shared_fsx.per_unit_storage_throughput or "NONE",
                shared_fsx.daily_automatic_backup_start_time or "NONE",
                shared_fsx.automatic_backup_retention_days or "NONE",
                shared_fsx.copy_tags_to_backups if shared_fsx.copy_tags_to_backups is not None else "NONE",
                shared_fsx.backup_id or "NONE",
                shared_fsx.auto_import_policy or "NONE",
                shared_fsx.fsx_storage_type or "NONE",
                shared_fsx.drive_cache_type or "NONE",
            ]
        )

        return fsx_id

    def _add_efs_storage(self, id: str, shared_efs: SharedEfs):
        """Add specific Cfn Resources to map the EFS storage."""
        # EFS FileSystem
        efs_id = shared_efs.file_system_id
        new_file_system = efs_id is None
        if not efs_id and shared_efs.mount_dir:
            efs_resource = efs.CfnFileSystem(
                scope=self,
                id=id,
                encrypted=shared_efs.encrypted,
                kms_key_id=shared_efs.kms_key_id,
                performance_mode=shared_efs.performance_mode,
                provisioned_throughput_in_mibps=shared_efs.provisioned_throughput,
                throughput_mode=shared_efs.throughput_mode,
            )
            efs_id = efs_resource.ref

        checked_availability_zones = []

        # Mount Targets for Compute Fleet
        compute_subnet_ids = self.config.compute_subnet_ids
        compute_node_sgs = self._get_compute_security_groups()

        for subnet_id in compute_subnet_ids:
            self._add_efs_mount_target(
                id, efs_id, compute_node_sgs, subnet_id, checked_availability_zones, new_file_system
            )

        # Mount Target for Head Node
        head_node_sgs = self._get_head_node_security_groups()
        self._add_efs_mount_target(
            id,
            efs_id,
            head_node_sgs,
            self.config.head_node.networking.subnet_id,
            checked_availability_zones,
            new_file_system,
        )

        # [shared_dir,efs_fs_id,performance_mode,efs_kms_key_id,provisioned_throughput,encrypted,
        # throughput_mode,exists_valid_head_node_mt,exists_valid_compute_mt]
        self.shared_storage_options[shared_efs.shared_storage_type] = ",".join(
            str(item)
            for item in [
                shared_efs.mount_dir,
                efs_id,
                shared_efs.performance_mode or "NONE",
                shared_efs.kms_key_id or "NONE",
                shared_efs.provisioned_throughput or "NONE",
                shared_efs.encrypted if shared_efs.encrypted is not None else "NONE",
                shared_efs.throughput_mode or "NONE",
                "NONE",  # Useless
                "NONE",  # Useless
            ]
        )
        return efs_id

    def _add_efs_mount_target(
        self,
        efs_cfn_resource_id,
        file_system_id,
        security_groups,
        subnet_id,
        checked_availability_zones,
        new_file_system,
    ):
        """Create a EFS Mount Point for the file system, if not already available on the same AZ."""
        availability_zone = AWSApi.instance().ec2.get_subnet_avail_zone(subnet_id)
        if availability_zone not in checked_availability_zones:
            if new_file_system or not AWSApi.instance().efs.get_efs_mount_target_id(file_system_id, availability_zone):
                efs.CfnMountTarget(
                    scope=self,
                    id="{0}MT{1}".format(efs_cfn_resource_id, availability_zone),
                    file_system_id=file_system_id,
                    security_groups=security_groups,
                    subnet_id=subnet_id,
                )
            checked_availability_zones.append(availability_zone)

    def _add_raid_volume(self, id_prefix: str, shared_ebs: SharedEbs):
        """Add specific Cfn Resources to map the RAID EBS storage."""
        ebs_ids = []
        for index in range(shared_ebs.raid.number_of_volumes):
            ebs_ids.append(StorageInfo(self._add_cfn_volume(f"{id_prefix}Volume{index}", shared_ebs), shared_ebs))

        # [shared_dir,raid_type,num_of_raid_volumes,volume_type,volume_size,volume_iops,encrypted,
        # ebs_kms_key_id,volume_throughput]
        self.shared_storage_options[shared_ebs.shared_storage_type] = ",".join(
            str(item)
            for item in [
                shared_ebs.mount_dir,
                shared_ebs.raid.raid_type,
                shared_ebs.raid.number_of_volumes,
                shared_ebs.volume_type,
                shared_ebs.size,
                shared_ebs.iops,
                shared_ebs.encrypted if shared_ebs.encrypted is not None else "NONE",
                shared_ebs.kms_key_id or "NONE",
                shared_ebs.throughput,
            ]
        )

        return ebs_ids

    def _add_ebs_volume(self, id: str, shared_ebs: SharedEbs):
        """Add specific Cfn Resources to map the EBS storage."""
        ebs_id = shared_ebs.volume_id
        if not ebs_id and shared_ebs.mount_dir:
            ebs_id = self._add_cfn_volume(id, shared_ebs)

        # Append mount dir to list of shared dirs
        self.shared_storage_options[shared_ebs.shared_storage_type] += (
            f",{shared_ebs.mount_dir}"
            if self.shared_storage_options[shared_ebs.shared_storage_type]
            else f"{shared_ebs.mount_dir}"
        )

        return ebs_id

    def _add_cfn_volume(self, id: str, shared_ebs: SharedEbs):
        return ec2.CfnVolume(
            scope=self,
            id=id,
            availability_zone=self.config.head_node.networking.availability_zone,
            encrypted=shared_ebs.encrypted,
            iops=shared_ebs.iops,
            throughput=shared_ebs.throughput,
            kms_key_id=shared_ebs.kms_key_id,
            size=shared_ebs.size,
            snapshot_id=shared_ebs.snapshot_id,
            volume_type=shared_ebs.volume_type,
        ).ref

    def _add_dynamodb_table(self):
        table = dynamodb.CfnTable(
            scope=self,
            id="DynamoDBTable",
            table_name=self._stack_name,
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
        table.cfn_options.update_replace_policy = core.CfnDeletionPolicy.RETAIN
        table.cfn_options.deletion_policy = core.CfnDeletionPolicy.DELETE
        return table

    def _add_head_node(self):
        head_node = self.config.head_node
        head_lt_security_groups = self._get_head_node_security_groups_full()

        # LT network interfaces
        head_lt_nw_interfaces = [
            ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                device_index=0,
                network_interface_id=self._head_eni.ref,
                associate_public_ip_address=head_node.networking.assign_public_ip,
            )
        ]
        for device_index in range(1, head_node.max_network_interface_count - 1):
            head_lt_nw_interfaces.append(
                ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                    device_index=device_index,
                    network_card_index=device_index,
                    groups=head_lt_security_groups,
                    subnet_id=head_node.networking.subnet_id,
                )
            )

        # Head node Launch Template
        head_node_launch_template = ec2.CfnLaunchTemplate(
            scope=self,
            id="HeadNodeLaunchTemplate",
            launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
                instance_type=head_node.instance_type,
                cpu_options=ec2.CfnLaunchTemplate.CpuOptionsProperty(core_count=head_node.vcpus, threads_per_core=1)
                if head_node.pass_cpu_options_in_launch_template
                else None,
                block_device_mappings=get_block_device_mappings(head_node, self.config.image.os),
                key_name=head_node.ssh.key_name,
                network_interfaces=head_lt_nw_interfaces,
                image_id=self.config.ami_id,
                ebs_optimized=head_node.is_ebs_optimized,
                iam_instance_profile=ec2.CfnLaunchTemplate.IamInstanceProfileProperty(
                    name=self.instance_profiles["HeadNode"]
                ),
                user_data=core.Fn.base64(
                    core.Fn.sub(
                        get_user_data_content("../resources/head_node/user_data.sh"),
                        {
                            **{"IamRoleName": self.instance_roles["HeadNode"]["RoleRef"]},
                            **get_common_user_data_env(head_node, self.config),
                        },
                    )
                ),
                tag_specifications=[
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="instance",
                        tags=get_default_instance_tags(
                            self._stack_name, self.config, head_node, "Master", self.shared_storage_mappings
                        )
                        + get_custom_tags(self.config),  # FIXME HeadNode
                    ),
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="volume",
                        tags=get_default_volume_tags(self._stack_name, "Master") + get_custom_tags(self.config),
                    ),  # FIXME HeadNode
                ],
            ),
        )

        # Metadata
        head_node_launch_template.add_metadata("Comment", "AWS ParallelCluster Head Node")
        # CloudFormation::Init metadata
        pre_install_action = head_node.get_custom_action(event=CustomActionEvent.NODE_START)
        post_install_action = head_node.get_custom_action(event=CustomActionEvent.NODE_CONFIGURED)
        dna_json = json.dumps(
            {
                "cfncluster": {
                    "stack_name": self._stack_name,
                    "cfn_raid_vol_ids": get_shared_storage_ids_by_type(
                        self.shared_storage_mappings, SharedStorageType.RAID
                    ),
                    "cfn_raid_parameters": get_shared_storage_options_by_type(
                        self.shared_storage_options, SharedStorageType.RAID
                    ),
                    "cfn_disable_hyperthreading_manually": "true"
                    if head_node.disable_simultaneous_multithreading_manually
                    else "false",
                    "cfn_base_os": self.config.image.os,
                    "cfn_preinstall": pre_install_action.script if pre_install_action else "NONE",
                    "cfn_preinstall_args": pre_install_action.args if pre_install_action else "NONE",
                    "cfn_postinstall": post_install_action.script if post_install_action else "NONE",
                    "cfn_postinstall_args": post_install_action.args if post_install_action else "NONE",
                    "cfn_region": self.region,
                    "cfn_efs": get_shared_storage_ids_by_type(self.shared_storage_mappings, SharedStorageType.EFS),
                    "cfn_efs_shared_dir": get_shared_storage_options_by_type(
                        self.shared_storage_options, SharedStorageType.EFS
                    ),  # FIXME
                    "cfn_fsx_fs_id": get_shared_storage_ids_by_type(
                        self.shared_storage_mappings, SharedStorageType.FSX
                    ),
                    "cfn_fsx_options": get_shared_storage_options_by_type(
                        self.shared_storage_options, SharedStorageType.FSX
                    ),
                    "cfn_volume": get_shared_storage_ids_by_type(self.shared_storage_mappings, SharedStorageType.EBS),
                    "cfn_scheduler": self.config.scheduling.scheduler,
                    "cfn_encrypted_ephemeral": "true"
                    if head_node.local_storage
                    and head_node.local_storage.ephemeral_volume
                    and head_node.local_storage.ephemeral_volume.encrypted
                    else "NONE",
                    "cfn_ephemeral_dir": head_node.local_storage.ephemeral_volume.mount_dir
                    if head_node.local_storage and head_node.local_storage.ephemeral_volume
                    else "/scratch",
                    "cfn_shared_dir": get_shared_storage_options_by_type(
                        self.shared_storage_options, SharedStorageType.EBS
                    ),
                    "cfn_proxy": head_node.networking.proxy if head_node.networking.proxy else "NONE",
                    "cfn_dns_domain": self.scheduler_resources.cluster_hosted_zone.name
                    if self._condition_is_slurm() and self.scheduler_resources.cluster_hosted_zone
                    else "",
                    "cfn_hosted_zone": self.scheduler_resources.cluster_hosted_zone.ref
                    if self._condition_is_slurm() and self.scheduler_resources.cluster_hosted_zone
                    else "",
                    "cfn_node_type": "MasterServer",  # FIXME
                    "cfn_cluster_user": OS_MAPPING[self.config.image.os]["user"],
                    "cfn_ddb_table": self.dynamodb_table.ref,
                    "cfn_log_group_name": self.log_group.log_group_name
                    if self.config.monitoring.logs.cloud_watch.enabled
                    else "NONE",
                    "dcv_enabled": head_node.dcv.enabled if head_node.dcv else "false",
                    "dcv_port": head_node.dcv.port if head_node.dcv else "NONE",
                    "enable_intel_hpc_platform": "true" if self.config.is_intel_hpc_platform_enabled else "false",
                    "cfn_cluster_cw_logging_enabled": "true" if self.config.is_cw_logging_enabled else "false",
                    "cluster_s3_bucket": self.bucket.name,
                    "cluster_config_s3_key": f"{self.bucket.artifact_directory}/configs/cluster-config.yaml",
                    "cluster_config_version": self.config.config_version,
                    "instance_types_data_s3_key": f"{self.bucket.artifact_directory}/configs/instance-types-data.json",
                },
                "run_list": f"recipe[aws-parallelcluster::{self.config.scheduling.scheduler}_config]",
            },
            indent=4,
        )

        cfn_init = {
            "configSets": {
                "default": [
                    "deployConfigFiles",
                    "cfnHupConfig",
                    "chefPrepEnv",
                    "shellRunPreInstall",
                    "chefConfig",
                    "shellRunPostInstall",
                    "chefFinalize",
                ],
                "update": ["deployConfigFiles", "chefUpdate"],
            },
            "deployConfigFiles": {
                "files": {
                    "/tmp/dna.json": {
                        "content": dna_json,
                        "mode": "000644",
                        "owner": "root",
                        "group": "root",
                        "encoding": "plain",
                    },
                    "/etc/chef/client.rb": {
                        "mode": "000644",
                        "owner": "root",
                        "group": "root",
                        "content": "cookbook_path ['/etc/chef/cookbooks']",
                    },
                    "/tmp/extra.json": {
                        "mode": "000644",
                        "owner": "root",
                        "group": "root",
                        "content": self.config.extra_chef_attributes,
                    },
                },
                "commands": {
                    "mkdir": {"command": "mkdir -p /etc/chef/ohai/hints"},
                    "touch": {"command": "touch /etc/chef/ohai/hints/ec2.json"},
                    "jq": {
                        "command": (
                            "jq --argfile f1 /tmp/dna.json --argfile f2 /tmp/extra.json -n '$f1 + $f2 "
                            "| .cfncluster = $f1.cfncluster + $f2.cfncluster' > /etc/chef/dna.json "
                            '|| ( echo "jq not installed"; cp /tmp/dna.json /etc/chef/dna.json )'
                        )
                    },
                },
            },
            "cfnHupConfig": {
                "files": {
                    "/etc/cfn/hooks.d/parallelcluster-update.conf": {
                        "content": core.Fn.sub(
                            (
                                "[parallelcluster-update]\n"
                                "triggers=post.update\n"
                                "path=Resources.HeadNodeLaunchTemplate.Metadata.AWS::CloudFormation::Init\n"
                                "action=PATH=/usr/local/bin:/bin:/usr/bin:/opt/aws/bin; "
                                "cfn-init -v --stack ${StackName} --role=${IamRoleName} "
                                "--resource HeadNodeLaunchTemplate --configsets update --region ${Region}\n"
                                "runas=root\n"
                            ),
                            {
                                "StackName": self._stack_name,
                                "Region": self.region,
                                "IamRoleName": self.instance_roles["HeadNode"]["RoleRef"],
                            },
                        ),
                        "mode": "000400",
                        "owner": "root",
                        "group": "root",
                    },
                    "/etc/cfn/cfn-hup.conf": {
                        "content": core.Fn.sub(
                            "[main]\nstack=${StackId}\nregion=${Region}\nrole=${IamRoleName}\ninterval=2",
                            {
                                "StackId": self.stack_id,
                                "Region": self.region,
                                "IamRoleName": self.instance_roles["HeadNode"]["RoleRef"],
                            },
                        ),
                        "mode": "000400",
                        "owner": "root",
                        "group": "root",
                    },
                }
            },
            "chefPrepEnv": {
                "commands": {
                    "chef": {
                        "command": (
                            "chef-client --local-mode --config /etc/chef/client.rb --log_level info "
                            "--logfile /var/log/chef-client.log --force-formatter --no-color "
                            "--chef-zero-port 8889 --json-attributes /etc/chef/dna.json "
                            "--override-runlist aws-parallelcluster::prep_env"
                        ),
                        "cwd": "/etc/chef",
                    }
                }
            },
            "shellRunPreInstall": {
                "commands": {"runpreinstall": {"command": "/opt/parallelcluster/scripts/fetch_and_run -preinstall"}}
            },
            "chefConfig": {
                "commands": {
                    "chef": {
                        "command": (
                            "chef-client --local-mode --config /etc/chef/client.rb --log_level info "
                            "--logfile /var/log/chef-client.log --force-formatter --no-color "
                            "--chef-zero-port 8889 --json-attributes /etc/chef/dna.json"
                        ),
                        "cwd": "/etc/chef",
                    }
                }
            },
            "shellRunPostInstall": {
                "commands": {"runpostinstall": {"command": "/opt/parallelcluster/scripts/fetch_and_run -postinstall"}}
            },
            "chefFinalize": {
                "commands": {
                    "chef": {
                        "command": (
                            "chef-client --local-mode --config /etc/chef/client.rb --log_level info "
                            "--logfile /var/log/chef-client.log --force-formatter --no-color "
                            "--chef-zero-port 8889 --json-attributes /etc/chef/dna.json "
                            "--override-runlist aws-parallelcluster::finalize"
                        ),
                        "cwd": "/etc/chef",
                    },
                    "bootstrap": {
                        "command": (
                            "[ ! -f /opt/parallelcluster/.bootstrapped ] && echo ${cookbook_version} "
                            "| tee /opt/parallelcluster/.bootstrapped || exit 0"
                        )  # TODO check
                    },
                }
            },
            "chefUpdate": {
                "commands": {
                    "chef": {
                        "command": (
                            "chef-client --local-mode --config /etc/chef/client.rb --log_level info "
                            "--logfile /var/log/chef-client.log --force-formatter --no-color "
                            "--chef-zero-port 8889 --json-attributes /etc/chef/dna.json "
                            "--override-runlist aws-parallelcluster::update_head_node"
                        ),
                        "cwd": "/etc/chef",
                    }
                }
            },
        }

        head_node_launch_template.add_metadata("AWS::CloudFormation::Init", cfn_init)
        head_node_instance = ec2.CfnInstance(
            self,
            id="MasterServer",  # FIXME
            launch_template=ec2.CfnInstance.LaunchTemplateSpecificationProperty(
                launch_template_id=head_node_launch_template.ref,
                version=head_node_launch_template.attr_latest_version_number,
            ),
        )
        head_node_instance.cfn_options.creation_policy = core.CfnCreationPolicy(
            resource_signal=core.CfnResourceSignal(count=1, timeout="PT30M")
        )

        return head_node_instance

    # -- Conditions -------------------------------------------------------------------------------------------------- #

    def _condition_create_iam_role(self, node: Union[HeadNode, BaseQueue]):
        """Iam role is created if instance role is not specified."""
        return not node.iam or not node.iam.instance_role

    def _condition_create_lambda_iam_role(self):
        return (
            not self.config.iam
            or not self.config.iam.roles
            or not self.config.iam.roles.custom_lambda_resources
            or self.config.iam.roles.get_param("custom_lambda_resources").implied
        )

    def _condition_create_s3_access_policies(self, node: Union[HeadNode, BaseQueue]):
        return node.iam and node.iam.s3_access

    def _condition_is_slurm(self):
        return self.config.scheduling.scheduler == "slurm"

    # -- Outputs ----------------------------------------------------------------------------------------------------- #

    def _add_outputs(self):
        # Storage filesystem Ids
        self._add_shared_storage_outputs()

        # ClusterUser
        core.CfnOutput(
            scope=self,
            id="ClusterUser",
            description="Username to login to head node",
            value=OS_MAPPING[self.config.image.os]["user"],
        )

        # Head Node Instance ID
        core.CfnOutput(
            scope=self,
            id="MasterInstanceID",  # FIXME
            description="ID of the head node instance",
            value=self.head_node_instance.ref,
        )

        # Head Node Private IP
        core.CfnOutput(
            scope=self,
            id="MasterPrivateIP",  # FIXME
            description="Private IP Address of the head node",
            value=self.head_node_instance.attr_private_ip,
        )

        core.CfnOutput(
            scope=self,
            id="MasterPrivateDnsName",  # FIXME
            description="Private DNS name of the head node",
            value=self.head_node_instance.attr_private_dns_name,
        )

        # Head Node Public IP
        head_public_ip = self.head_node_instance.attr_public_ip
        if head_public_ip:
            core.CfnOutput(
                scope=self,
                id="MasterPublicIP",  # FIXME
                description="Private IP Address of the head node",
                value=head_public_ip,
            )

        # ResourcesS3Bucket
        core.CfnOutput(
            scope=self,
            id="ResourcesS3Bucket",
            description="S3 user bucket where AWS ParallelCluster resources are stored",
            value=self.bucket.name,
        )

        # ArtifactS3RootDirectory
        core.CfnOutput(
            scope=self,
            id="ArtifactS3RootDirectory",
            description="Root directory in S3 bucket where cluster artifacts are stored",
            value=self.bucket.artifact_directory,
        )

        # BatchComputeEnvironmentArn
        # BatchJobQueueArn
        # BatchJobDefinitionArn
        # BatchJobDefinitionMnpArn
        # BatchUserRole
        # TODO: take values from Batch resources

        core.CfnOutput(id="Scheduler", scope=self, value=self.config.scheduling.scheduler)

    def _add_shared_storage_outputs(self):
        """Add the ids of the managed filesystem to the Stack Outputs."""
        for storage_type, storage_list in self.shared_storage_mappings.items():
            core.CfnOutput(
                scope=self,
                id="{0}Ids".format(storage_type.name),
                description="{0} Filesystem IDs".format(storage_type.name),
                value=",".join(storage.id for storage in storage_list),
            )
