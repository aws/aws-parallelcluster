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

from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_efs as efs
from aws_cdk import aws_fsx as fsx
from aws_cdk import core
from aws_cdk.aws_ec2 import (
    CfnEIP,
    CfnEIPAssociation,
    CfnNetworkInterface,
    CfnSecurityGroup,
    CfnSecurityGroupEgress,
    CfnSecurityGroupIngress,
)
from aws_cdk.aws_iam import (
    CfnInstanceProfile,
    CfnPolicy,
    CfnRole,
    Effect,
    PolicyDocument,
    PolicyStatement,
    ServicePrincipal,
)
from aws_cdk.aws_lambda import CfnFunction
from aws_cdk.core import CfnCustomResource, CfnOutput, CfnStack, Fn

from common.aws.aws_api import AWSApi
from pcluster.models.cluster import HeadNode, SharedEbs, SharedEfs, SharedFsx, SharedStorageType
from pcluster.models.cluster_slurm import SlurmCluster


# pylint: disable=too-many-lines
class ClusterStack(core.Stack):
    """Create the CloudFormation stack template for the Cluster."""

    def __init__(self, scope: core.Construct, construct_id: str, cluster: SlurmCluster, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self._cluster = cluster

        self._init_mappings()
        self._add_resources()
        self._add_ouputs()

    # -- Mappings ---------------------------------------------------------------------------------------------------- #
    def _init_mappings(self):
        # OS Features
        self.os_features = {
            "centos7": {"User": "centos", "RootDevice": "/dev/sda1"},
            "centos8": {"User": "centos", "RootDevice": "/dev/sda1"},
            "alinux": {"User": "ec2-user", "RootDevice": "/dev/xvda"},
            "alinux2": {"User": "ec2-user", "RootDevice": "/dev/xvda"},
            "ubuntu1604": {"User": "ubuntu", "RootDevice": "/dev/sda1"},
            "ubuntu1804": {"User": "ubuntu", "RootDevice": "/dev/sda1"},
        }

        # Storage filesystem Ids
        self._storage_resource_ids = {storage_type: [] for storage_type in SharedStorage.Type}

    # -- Resources --------------------------------------------------------------------------------------------------- #
    def _add_resources(self):
        # CloudWatchLogsSubstack
        # TODO: inline cw-logs-substack

        # RootRole
        if self._condition_create_ec2_iam_role():
            self.root_iam_role = self._add_root_iam_role()

        # RootInstanceProfile
        self._add_root_instance_profile()

        # ParallelClusterPolicies
        if self._condition_create_ec2_iam_role():
            self._add_parallelcluster_policies()

        # ParallelClusterHITPolicies
        if self._condition_add_hit_iam_policies():
            self._add_parallelcluster_hit_policies()

        # S3AccessPolicies
        if self._condition_create_s3_access_policies():
            self._add_s3_access_policies()

        # MasterEIP
        if self._cluster.head_node.networking.assign_public_ip:
            self._head_eip = CfnEIP(scope=self, id="MasterEIP", domain="vpc")

        # ParallelCluster managed security groups
        self._add_security_groups()

        # MasterENI
        self.head_eni = self._add_head_eni()

        # AdditionalCfnStack
        if self._cluster.additional_resources:
            CfnStack(scope=self, id="AdditionalCfnStack", template_url=self._cluster.additional_resources)

        # AWSBatchStack
        # TODO: inline resources

        # CleanupResourcesFunctionExecutionRole
        if self._condition_create_lambda_iam_role():
            self._add_iam_lambda_role()

        # CleanupResourcesFunction
        self.cleanup_resources_function = self._add_cleanup_resources_function()

        # CleanupResourcesS3BucketCustomResource
        self.cleanup_resources_bucket_custom_resource = self._add_cleanup_resources_bucket_custom_resource()

        # TerminateComputeFleetCustomResource
        self._add_terminate_compute_fleet_custom_resource()

        # RAIDSubstack
        # TODO: inline resources

        # MasterServerSubstack
        # TODO: double check head node creation
        self._add_head_node()

        # ComputeFleetHITSubstack
        # TODO: inline resources

        # CloudWatchDashboardSubstack
        # TODO: inline resources

        if self._cluster.shared_storage:
            for storage in self._cluster.shared_storage:
                self._add_shared_storage(storage)

    def _add_terminate_compute_fleet_custom_resource(self):
        if self._condition_create_hit_substack():
            self.terminate_compute_fleet_custom_resource = CfnCustomResource(
                scope=self,
                id="TerminateComputeFleetCustomResource",
                service_token=self.cleanup_resources_function.attr_arn,
            )
            self.terminate_compute_fleet_custom_resource.add_property_override("StackName", self.stack_name)
            self.terminate_compute_fleet_custom_resource.add_property_override("Action", "TERMINATE_EC2_INSTANCES")

            # TODO: add depends_on resources from CloudWatchLogsSubstack, ComputeFleetHITSubstack
            # self.terminate_compute_fleet_custom_resource.add_depends_on(...)

    def _add_cleanup_resources_function(self):
        return CfnFunction(
            scope=self,
            id="CleanupResourcesFunction",
            function_name=Fn.sub(
                "pcluster-CleanupResources-${StackId}", {"StackId": Fn.select(2, Fn.split("/", self.stack_id))}
            ),
            code=CfnFunction.CodeProperty(
                s3_bucket=self._cluster.cluster_s3_bucket,
                s3_key="{0}/custom_resources_code/artifacts.zip".format(self._cluster.artifacts_s3_root_directory),
            ),
            handler="cleanup_resources.handler",
            memory_size=128,
            role=self.cleanup_resources_function_execution_role.attr_arn
            if self._condition_create_lambda_iam_role()
            else self.format_arn(
                service="iam", region="", resource="role/{0}".format(self._cluster.iam.roles.custom_lambda_resources)
            ),
            runtime="python3.8",
            timeout=900,
        )

    def _add_head_eni(self):
        head_eni_groupset = []
        if self._cluster.head_node.networking.additional_security_groups:
            head_eni_groupset.extend(self._cluster.head_node.networking.additional_security_groups)
        if self._condition_create_head_security_group():
            head_eni_groupset.append(self._head_security_group.ref)
        elif self._cluster.head_node.networking.security_groups:
            head_eni_groupset.extend(self._cluster.head_node.networking.security_groups)
        head_eni = CfnNetworkInterface(
            scope=self,
            id="MasterENI",
            description="AWS ParallelCluster head node interface",
            subnet_id=self._cluster.head_node.networking.subnet_id,
            source_dest_check=False,
            group_set=head_eni_groupset,
        )
        # AssociateEIP
        if self._cluster.head_node.networking.assign_public_ip:
            CfnEIPAssociation(
                scope=self,
                id="AssociateEIP",
                allocation_id=self._head_eip.attr_allocation_id,
                network_interface_id=head_eni.ref,
            )
        return head_eni

    def _add_security_groups(self):
        # MasterSecurityGroup
        if self._condition_create_head_security_group():
            self._head_security_group = self._add_head_security_group()
        # ComputeSecurityGroup
        if self._condition_create_compute_security_group():
            self._compute_security_group = self._add_compute_security_group()
        # MasterSecurityGroupIngress
        # Access to head node from compute nodes
        if self._condition_create_head_security_group() and self._condition_create_compute_security_group():
            CfnSecurityGroupIngress(
                scope=self,
                id="MasterSecurityGroupIngress",
                ip_protocol="-1",
                from_port=0,
                to_port=65535,
                source_security_group_id=self._compute_security_group.ref,
                group_id=self._head_security_group.ref,
            )
        if self._condition_create_compute_security_group():
            # ComputeSecurityGroupEgress
            # Access to other compute nodes from compute nodes
            compute_security_group_egress = CfnSecurityGroupEgress(
                scope=self,
                id="ComputeSecurityGroupEgress",
                ip_protocol="-1",
                from_port=0,
                to_port=65535,
                destination_security_group_id=self._compute_security_group.ref,
                group_id=self._compute_security_group.ref,
            )

            # ComputeSecurityGroupNormalEgress
            # Internet access from compute nodes
            CfnSecurityGroupEgress(
                scope=self,
                id="ComputeSecurityGroupNormalEgress",
                ip_protocol="-1",
                from_port=0,
                to_port=65535,
                cidr_ip="0.0.0.0/0",
                group_id=self._compute_security_group.ref,
            ).add_depends_on(compute_security_group_egress)

            # ComputeSecurityGroupIngress
            # Access to compute nodes from other compute nodes
            CfnSecurityGroupIngress(
                scope=self,
                id="ComputeSecurityGroupIngress",
                ip_protocol="-1",
                from_port=0,
                to_port=65535,
                source_security_group_id=self._compute_security_group.ref,
                group_id=self._compute_security_group.ref,
            )

    def _add_compute_security_group(self):
        return CfnSecurityGroup(
            scope=self,
            id="ComputeSecurityGroup",
            group_description="Allow access to resources in subnets behind front",
            vpc_id=self._cluster.vpc_id,
            security_group_ingress=[
                # Access from master security group
                CfnSecurityGroup.IngressProperty(
                    source_security_group_id=self._head_security_group.ref,
                    ip_protocol="-1",
                    from_port=0,
                    to_port=65535,
                )
            ],
        )

    def _add_s3_access_policies(self):
        read_only_s3_resources = [
            s3_access.bucket_name for s3_access in self._cluster.iam.s3_access if s3_access.type == "READ_ONLY"
        ]
        read_write_s3_resources = [
            s3_access.bucket_name for s3_access in self._cluster.iam.s3_access if s3_access.type != "READ_ONLY"
        ]
        s3_access_policy = CfnPolicy(
            scope=self,
            id="S3AccessPolicies",
            policy_document=PolicyDocument(statements=[]),
            roles=[self.root_iam_role.ref],
            policy_name="S3Access",
        )
        if read_only_s3_resources:
            s3_access_policy.policy_document.add_statements(
                PolicyStatement(
                    sid="S3Read",
                    effect=Effect.ALLOW,
                    actions=["s3:Get*", "s3:List*"],
                    resources=read_only_s3_resources,
                )
            )
        if read_write_s3_resources:
            s3_access_policy.policy_document.add_statements(
                PolicyStatement(
                    sid="S3ReadWrite", effect=Effect.ALLOW, actions=["s3:*"], resources=read_write_s3_resources
                )
            )

    def _add_root_instance_profile(self):
        root_instance_profile_roles = [
            self.root_iam_role.ref if hasattr(self, "root_iam_role") else None,
            self._cluster.head_iam_role,
            self._cluster.compute_iam_role,
        ]
        CfnInstanceProfile(
            scope=self,
            id="RootInstanceProfile",
            roles=[role for role in root_instance_profile_roles if role is not None],
            path="/",
        )

    def _add_root_iam_role(self):
        return CfnRole(
            scope=self,
            id="RootRole",
            managed_policy_arns=self._cluster.iam.additional_iam_policies if self._cluster.iam else None,
            assume_role_policy_document=PolicyDocument(
                statements=[
                    PolicyStatement(
                        effect=Effect.ALLOW,
                        principals=[
                            ServicePrincipal(
                                service="ec2.{0}".format(self.url_suffix),
                            )
                        ],
                        actions=["sts:AssumeRole"],
                    )
                ]
            ),
            path="/",
        )

    def _add_iam_lambda_role(self):
        s3_policy_actions = ["s3:DeleteObject", "s3:DeleteObjectVersion", "s3:ListBucket", "s3:ListBucketVersions"]
        if self._cluster.remove_s3_bucket_on_deletion:
            s3_policy_actions.append("s3:DeleteBucket")
        self.cleanup_resources_function_execution_role = CfnRole(
            scope=self,
            id="CleanupResourcesFunctionExecutionRole",
            assume_role_policy_document=PolicyDocument(
                statements=[
                    PolicyStatement(
                        actions=["sts:AssumeRole"],
                        effect=Effect.ALLOW,
                        principals=[ServicePrincipal(service="lambda.amazonaws.com")],
                    )
                ],
            ),
            path="/",
            policies=[
                CfnRole.PolicyProperty(
                    policy_document=PolicyDocument(
                        statements=[
                            PolicyStatement(
                                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                                effect=Effect.ALLOW,
                                resources=[self.format_arn(service="logs", account="*", region="*", resource="*")],
                                sid="CloudWatchLogsPolicy",
                            ),
                            PolicyStatement(
                                actions=s3_policy_actions,
                                effect=Effect.ALLOW,
                                resources=[
                                    self.format_arn(
                                        service="s3", account="", region="", resource=self._cluster.cluster_s3_bucket
                                    ),
                                    self.format_arn(
                                        service="s3",
                                        account="",
                                        region="",
                                        resource="{0}/{1}/*".format(
                                            self._cluster.cluster_s3_bucket, self._cluster.artifacts_s3_root_directory
                                        ),
                                    ),
                                ],
                                sid="S3BucketPolicy",
                            ),
                        ],
                    ),
                    policy_name="LambdaPolicy",
                ),
            ],
        )
        if self._condition_create_hit_substack():
            self.cleanup_resources_function_execution_role.policies[0].policy_document.add_statements(
                PolicyStatement(
                    actions=["ec2:DescribeInstances"], resources=["*"], effect=Effect.ALLOW, sid="DescribeInstances"
                ),
                PolicyStatement(
                    actions=["ec2:TerminateInstances"],
                    resources=["*"],
                    effect=Effect.ALLOW,
                    conditions=[{"StringEquals": {"ec2:ResourceTag/Application": self.stack_name}}],
                    sid="FleetTerminatePolicy",
                ),
            )

    def _add_parallelcluster_policies(self):
        CfnPolicy(
            scope=self,
            id="ParallelClusterPolicies",
            policy_name="parallelcluster",
            policy_document=PolicyDocument(
                statements=[
                    PolicyStatement(
                        sid="Ec2",
                        actions=[
                            "ec2:DescribeVolumes",
                            "ec2:AttachVolume",
                            "ec2:DescribeInstanceAttribute",
                            "ec2:DescribeInstanceStatus",
                            "ec2:DescribeInstances",
                            "ec2:DescribeInstanceTypes",
                        ],
                        effect=Effect.ALLOW,
                        resources=["*"],
                    ),
                    PolicyStatement(
                        sid="DynamoDBList", actions=["dynamodb:ListTables"], effect=Effect.ALLOW, resources=["*"]
                    ),
                    PolicyStatement(
                        sid="SQSQueue",
                        actions=[
                            "sqs:SendMessage",
                            "sqs:ReceiveMessage",
                            "sqs:ChangeMessageVisibility",
                            "sqs:DeleteMessage",
                            "sqs:GetQueueUrl",
                        ],
                        effect=Effect.ALLOW,
                        resources=[self.format_arn(service="sqs", resource=self.stack_name)],
                    ),
                    PolicyStatement(
                        sid="Cloudformation",
                        actions=[
                            "cloudformation:DescribeStacks",
                            "cloudformation:DescribeStackResource",
                            "cloudformation:SignalResource",
                        ],
                        effect=Effect.ALLOW,
                        resources=[self.format_arn(service="cloudformation", resource="stack/parallelcluster-*/*")],
                    ),
                    PolicyStatement(
                        sid="DynamoDBTable",
                        actions=[
                            "dynamodb:PutItem",
                            "dynamodb:BatchWriteItem",
                            "dynamodb:GetItem",
                            "dynamodb:DeleteItem",
                            "dynamodb:DescribeTable",
                        ],
                        effect=Effect.ALLOW,
                        resources=[self.format_arn(service="dynamodb", resource="table/${AWS::StackName}")],
                    ),
                    PolicyStatement(
                        sid="S3GetObj",
                        actions=["s3:GetObject"],
                        effect=Effect.ALLOW,
                        resources=[
                            self.format_arn(
                                service="s3",
                                account=None,  # No account ID needed here
                                region=None,  # No region needed here
                                resource="{0}-aws-parallelcluster/*".format(self.region),
                            )
                        ],
                    ),
                    PolicyStatement(
                        sid="S3PutObj",
                        actions=["s3:PutObject"],
                        effect=Effect.ALLOW,
                        resources=[
                            self.format_arn(
                                service="s3",
                                account=None,  # No account ID needed here
                                region=None,  # No region needed here
                                resource="{0}/{1}/batch/".format(
                                    self._cluster.cluster_s3_bucket, self._cluster.artifacts_s3_root_directory
                                ),
                            )
                        ],
                    ),
                    PolicyStatement(
                        sid="FSx", actions=["fsx:DescribeFileSystems"], effect=Effect.ALLOW, resources=["*"]
                    ),
                    PolicyStatement(
                        sid="BatchJobPassRole",
                        actions=["iam:PassRole"],
                        effect=Effect.ALLOW,
                        resources=[self.format_arn(service="iam", resource="role/parallelcluster-*")],
                    ),
                    PolicyStatement(
                        sid="DcvLicense",
                        actions=["s3:GetObject"],
                        effect=Effect.ALLOW,
                        resources=[
                            self.format_arn(
                                service="s3",
                                account=None,  # No account ID needed here
                                region=None,  # No region needed here
                                resource="dcv-license.{0}/*".format(self.region),
                            )
                        ],
                    ),
                ]
            ),
            roles=[self.root_iam_role.ref],
        )

    def _add_parallelcluster_hit_policies(self):
        CfnPolicy(
            scope=self,
            id="ParallelClusterHITPolicies",
            policy_name="parallelcluster-hit",
            policy_document=PolicyDocument(
                statements=[
                    PolicyStatement(
                        sid="EC2Terminate",
                        effect=Effect.ALLOW,
                        actions=["ec2:TerminateInstances"],
                        resources=["*"],
                        conditions=[{"StringEquals": {"ec2:ResourceTag/Application": self.stack_name}}],
                    ),
                    PolicyStatement(
                        sid="EC2",
                        effect=Effect.ALLOW,
                        actions=[
                            "ec2:DescribeInstances",
                            "ec2:DescribeLaunchTemplates",
                            "ec2:RunInstances",
                            "ec2:DescribeInstanceStatus",
                            "ec2:CreateTags",
                        ],
                        resources=["*"],
                    ),
                    PolicyStatement(
                        sid="ResourcesS3Bucket",
                        effect=Effect.ALLOW,
                        actions=["s3:ListBucket", "s3:ListBucketVersions", "s3:GetObject*", "s3:PutObject*"]
                        if self._cluster.remove_s3_bucket_on_deletion
                        else ["s3:*"],
                        resources=[
                            self.format_arn(
                                service="s3", account="", region="", resource=self._cluster.cluster_s3_bucket
                            ),
                            self.format_arn(
                                service="s3",
                                account="",
                                region="",
                                resource="{0}/{1}/*".format(
                                    self._cluster.cluster_s3_bucket, self._cluster.artifacts_s3_root_directory
                                ),
                            ),
                        ],
                    ),
                    PolicyStatement(
                        sid="DynamoDBTableQuery",
                        effect=Effect.ALLOW,
                        actions=["dynamodb:Query"],
                        resources=[
                            self.format_arn(service="dynamodb", resource="table/{0}".format(self.stack_name)),
                            self.format_arn(service="dynamodb", resource="table/{0}/index/*".format(self.stack_name)),
                        ],
                    ),
                ]
            ),
            roles=[self.root_iam_role.ref],
        )

    def _add_head_security_group(self):
        head_security_group_ingress = [
            # SSH access
            CfnSecurityGroup.IngressProperty(
                ip_protocol="tcp",
                from_port=22,
                to_port=22,
                cidr_ip=self._cluster.head_node.ssh.allowed_ips,
            ),
        ]
        if self._cluster.head_node.dcv and self._cluster.head_node.dcv.enabled:
            head_security_group_ingress.append(
                # DCV access
                CfnSecurityGroup.IngressProperty(
                    ip_protocol="tcp",
                    from_port=self._cluster.head_node.dcv.port,
                    to_port=self._cluster.head_node.dcv.port,
                    cidr_ip=self._cluster.head_node.dcv.allowed_ips,
                )
            )
        return CfnSecurityGroup(
            scope=self,
            id="MasterSecurityGroup",
            group_description="Enable access to the head node",
            vpc_id=self._cluster.vpc_id,
            security_group_ingress=head_security_group_ingress,
        )

    def _add_cleanup_resources_bucket_custom_resource(self):
        cleanup_resources_bucket_custom_resource = CfnCustomResource(
            scope=self,
            id="CleanupResourcesS3BucketCustomResource",
            service_token=self.cleanup_resources_function.attr_arn,
        )
        cleanup_resources_bucket_custom_resource.add_property_override(
            "ResourcesS3Bucket", self._cluster.cluster_s3_bucket
        )
        cleanup_resources_bucket_custom_resource.add_property_override(
            "ArtifactS3RootDirectory", self._cluster.artifacts_s3_root_directory
        )
        cleanup_resources_bucket_custom_resource.add_property_override(
            "RemoveBucketOnDeletion", self._cluster.remove_s3_bucket_on_deletion
        )
        cleanup_resources_bucket_custom_resource.add_property_override("Action", "DELETE_S3_ARTIFACTS")
        return cleanup_resources_bucket_custom_resource

    def _add_shared_storage(self, storage: SharedStorage):
        """Add specific Cfn Resources to map the shared storage and store the output filesystem id."""
        storage_id = None
        cfn_resource_id = "{0}{1}".format(
            storage.shared_storage_type.name, len(self._storage_resource_ids[storage.shared_storage_type])
        )
        if storage.shared_storage_type == SharedStorage.Type.FSX:
            storage_id = self._add_fsx_storage(cfn_resource_id, storage)
        elif storage.shared_storage_type == SharedStorage.Type.EBS:
            storage_id = self._add_ebs_volume(cfn_resource_id, storage)
        elif storage.shared_storage_type == SharedStorage.Type.EFS:
            storage_id = self._add_efs_storage(cfn_resource_id, storage)

        # Store filesystem id
        storage_ids_list = self._storage_resource_ids[storage.shared_storage_type]
        if not storage_ids_list:
            storage_ids_list = []
            self._storage_resource_ids[storage.shared_storage_type] = storage_ids_list
        storage_ids_list.append(storage_id)

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
                subnet_ids=self._cluster.compute_subnet_ids,
                security_group_ids=self._cluster.compute_security_groups,
            )
            fsx_id = fsx_resource.ref

        return fsx_id

    def _add_efs_storage(self, id: str, shared_efs: SharedEfs):
        """Add specific Cfn Resources to map the EFS storage."""
        # EFS FileSystem
        efs_id = shared_efs.file_system_id
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
        compute_subnet_ids = self._cluster.compute_subnet_ids
        for subnet_id in compute_subnet_ids:
            self._add_efs_mount_target(
                id, efs_id, self._cluster.compute_security_groups, subnet_id, checked_availability_zones
            )

        # Mount Target for Head Node
        self._add_efs_mount_target(
            id,
            efs_id,
            self._cluster.head_node.networking.security_groups,
            self._cluster.head_node.networking.subnet_id,
            checked_availability_zones,
        )
        return efs_id

    def _add_efs_mount_target(
        self, efs_cfn_resource_id, file_system_id, security_groups, subnet_id, checked_availability_zones
    ):
        """Create a EFS Mount Point for the file system, if not already available on the same AZ."""
        availability_zone = AWSApi.instance().ec2.get_availability_zone_of_subnet(subnet_id)
        if availability_zone not in checked_availability_zones:
            mount_target_id = AWSApi.instance().efs.get_efs_mount_target_id(file_system_id, availability_zone)

            if not mount_target_id:
                efs.CfnMountTarget(
                    scope=self,
                    id="{0}MT{1}".format(efs_cfn_resource_id, availability_zone),
                    file_system_id=file_system_id,
                    security_groups=security_groups,
                    subnet_id=subnet_id,
                )
            checked_availability_zones.append(availability_zone)

    def _add_ebs_volume(self, id: str, shared_ebs: SharedEbs):
        """Add specific Cfn Resources to map the EBS storage."""
        ebs_id = shared_ebs.volume_id
        if not ebs_id and shared_ebs.mount_dir:
            ebs_resource = ec2.CfnVolume(
                scope=self,
                id=id,
                availability_zone=AWSApi.instance().ec2.get_availability_zone_of_subnet(
                    self._cluster.head_node.networking.subnet_id
                ),
                encrypted=shared_ebs.encrypted,
                iops=shared_ebs.iops,
                throughput=shared_ebs.throughput,
                kms_key_id=shared_ebs.kms_key_id,
                size=shared_ebs.size,
                snapshot_id=shared_ebs.snapshot_id,
                volume_type=shared_ebs.volume_type,
            )
            ebs_id = ebs_resource.ref

        return ebs_id

    def _add_head_node(self):
        # TODO: use attributes from head_node instead of using these static variables. Double check compliance with
        # MasterServerSubStack
        master_instance_type = self._cluster.head_node.instance_type
        master_core_count = "-1,true"
        # compute_core_count = "-1"
        key_name = self._cluster.head_node.ssh.key_name
        root_device = self.os_features[self._cluster.image.os]["RootDevice"]
        root_volume_size = 10
        # proxy_server = "proxy_server"
        placement_group = "placement_group"
        # update_waiter_function_arn = "update_waiter_function_arn"
        # use_master_public_ip = True
        master_network_interfaces_count = 5
        head_eni = "head_eni"
        master_security_groups = ["master_security_groups"]
        master_subnet_id = "master_subnet_id"
        image_id = "image_id"
        iam_instance_profile = "iam_instance_profile"

        # Conditions
        master_core_info = master_core_count.split(",")
        disable_master_hyperthreading = master_core_info[0] != -1 and master_core_info[0] != "NONE"
        # disable_compute_hyperthreading = master_core_info != -1 and master_core_info != "NONE"
        disable_hyperthreading_via_cpu_options = disable_master_hyperthreading and master_core_info[1] == "true"
        # disable_hyperthreading_manually = disable_master_hyperthreading and not disable_hyperthreading_via_cpu_options
        is_master_instance_ebs_opt = master_instance_type not in [
            "cc2.8xlarge",
            "cr1.8xlarge",
            "m3.medium",
            "m3.large",
            "c3.8xlarge",
            "c3.large",
            "",
        ]
        # use_proxy = proxy_server != "NONE"
        use_placement_group = placement_group != "NONE"
        # has_update_waiter_function = update_waiter_function_arn != "NONE"
        # has_master_public_ip = use_master_public_ip == "true"
        # use_nic1 = master_network_interfaces_count ... TODO

        cpu_options = ec2.CfnLaunchTemplate.CpuOptionsProperty(
            core_count=int(master_core_info[0]),
            threads_per_core=1,
        )
        block_device_mappings = []
        for _, (device_name_index, virtual_name_index) in enumerate(zip(list(map(chr, range(97, 121))), range(0, 24))):
            device_name = "/dev/xvdb{0}".format(device_name_index)
            virtual_name = "ephemeral{0}".format(virtual_name_index)
            block_device_mappings.append(
                ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(device_name=device_name, virtual_name=virtual_name)
            )

        block_device_mappings.append(
            ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                device_name=root_device,
                ebs=ec2.CfnLaunchTemplate.EbsProperty(
                    volume_size=root_volume_size,
                    volume_type="gp2",
                ),
            )
        )

        tags_raw = [
            ("Application", self.stack_name),
            ("Name", "Master"),
            ("aws-parallelcluster-node-type", "Master"),
            ("ClusterName", "parallelcluster-{0}".format(self.stack_name)),
            # ... TODO
        ]
        tags = []
        for key, value in tags_raw:
            tags.append(core.CfnTag(key=key, value=value))
        tag_specifications = [
            ec2.CfnLaunchTemplate.TagSpecificationProperty(resource_type="instance", tags=tags),
            ec2.CfnLaunchTemplate.TagSpecificationProperty(resource_type="volume", tags=tags),  # FIXME
        ]

        network_interfaces = [
            ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                network_interface_id=head_eni,
                device_index=0,
            )
        ]
        for index in range(1, master_network_interfaces_count + 1):
            network_interfaces.append(
                ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                    device_index=index,
                    network_card_index=index,
                    groups=master_security_groups,
                    subnet_id=master_subnet_id,
                )
            )

        launch_template_data = ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
            instance_type=master_instance_type,
            cpu_options=cpu_options if disable_hyperthreading_via_cpu_options else None,
            block_device_mappings=block_device_mappings,
            key_name=key_name,
            tag_specifications=tag_specifications,
            network_interfaces=network_interfaces,
            image_id=image_id,
            ebs_optimized=is_master_instance_ebs_opt,
            iam_instance_profile=ec2.CfnLaunchTemplate.IamInstanceProfileProperty(name=iam_instance_profile),
            placement=ec2.CfnLaunchTemplate.PlacementProperty(
                group_name=placement_group if use_placement_group else None
            ),
            # user_data= TODO
            # https://stackoverflow.com/questions/57753032/how-to-obtain-pseudo-parameters-user-data-with-aws-cdk
        )

        launch_template = ec2.CfnLaunchTemplate(
            scope=self, id="MasterServerLaunchTemplate", launch_template_data=launch_template_data
        )

        master_instance = ec2.CfnInstance(
            self,
            id="MasterServer",
            launch_template=ec2.CfnInstance.LaunchTemplateSpecificationProperty(
                launch_template_id=launch_template.ref, version=launch_template.attr_latest_version_number
            ),
        )

        core.CfnOutput(
            self,
            id="privateip",
            description="Private IP Address of the Master host",
            value=master_instance.attr_public_ip,
        )
        core.CfnOutput(
            self,
            id="publicip",
            description="Public IP Address of the Master host",
            value=master_instance.attr_public_ip,
        )
        core.CfnOutput(
            self,
            id="dnsname",
            description="Private DNS name of the Master host",
            value=master_instance.attr_private_dns_name,
        )

        # TODO metadata?

        # https://docs.aws.amazon.com/cdk/latest/guide/use_cfn_template.html
        # with open('master-server-substack.cfn.yaml', 'r') as f:
        # template = yaml.load(f, Loader=yaml.SafeLoader)
        # include = core.CfnInclude(self, 'ExistingInfrastructure',
        #    template=template,
        # )

    # -- Conditions -------------------------------------------------------------------------------------------------- #

    def _condition_create_ec2_iam_role(self):
        """Root role is created if head instance role or one of compute node instance roles is not specified."""
        # TODO: split root role in head and compute roles
        head_node = self._cluster.head_node
        role_needed = (
            not head_node.iam
            or not head_node.iam.roles
            or not head_node.iam.roles.instance_role
            or head_node.iam.roles.instance_role == "AUTO"
        )

        if not role_needed:
            for queue in self._cluster.scheduling.queues:
                role_needed = (
                    not queue.head_node.iam
                    or not queue.iam.roles
                    or not queue.iam.roles.instance_role
                    or queue.iam.roles.instance_role == "AUTO"
                )
                if role_needed:
                    break
        return role_needed

    def _condition_create_lambda_iam_role(self):
        return (
            not self._cluster.iam
            or not self._cluster.iam.roles
            or not self._cluster.iam.roles.custom_lambda_resources
            or self._cluster.iam.roles.get_param("custom_lambda_resources").implied
        )

    def _condition_create_s3_access_policies(self):
        return self._cluster.iam and self._cluster.iam.s3_access

    def _condition_add_hit_iam_policies(self):
        return self._condition_create_ec2_iam_role() and self._cluster.scheduling.scheduler == "slurm"

    def _condition_create_compute_security_group(self):
        # Compute security group must be created if at list one queue's networking does not specify security groups
        condition = False
        for queue in self._cluster.scheduling.queues:
            if not queue.networking.security_groups:
                condition = True
        return condition

    def _condition_create_head_security_group(self):
        return not self._cluster.head_node.networking.security_groups

    def _condition_create_hit_substack(self):
        return self._cluster.scheduling.scheduler == "slurm"

    # -- Outputs ----------------------------------------------------------------------------------------------------- #

    def _add_ouputs(self):
        # Storage filesystem Ids
        self._add_shared_storage_outputs()

        # ClusterUser
        CfnOutput(
            scope=self,
            id="ClusterUser",
            description="Username to login to head node",
            value=self.os_features[self._cluster.image.os]["User"],
        )

        # MasterPrivateIP
        # TODO: take from created head node
        head_private_ip = "10.0.0.2"

        # MasterPublicIP
        # TODO: take from created head node
        head_public_ip = "176.32.103.200"

        # GangliaPrivateURL
        CfnOutput(
            scope=self,
            id="GangliaPrivateURL",
            description="Private URL to access Ganglia (disabled by default)",
            value="http://{0}/ganglia/".format(head_private_ip),
        )

        # GangliaPublicURL
        CfnOutput(
            scope=self,
            id="GangliaPublicURL",
            description="Public URL to access Ganglia (disabled by default)",
            value="http://{0}/ganglia/".format(head_public_ip),
        )

        # ResourcesS3Bucket
        CfnOutput(
            scope=self,
            id="ResourcesS3Bucket",
            description="S3 user bucket where AWS ParallelCluster resources are stored",
            value=self._cluster.cluster_s3_bucket,
        )

        # ArtifactS3RootDirectory
        CfnOutput(
            scope=self,
            id="ArtifactS3RootDirectory",
            description="Root directory in S3 bucket where cluster artifacts are stored",
            value=self._cluster.artifacts_s3_root_directory,
        )

        # BatchComputeEnvironmentArn
        # BatchJobQueueArn
        # BatchJobDefinitionArn
        # BatchJobDefinitionMnpArn
        # BatchUserRole
        # TODO: take values from Batch resources

        # IsHITCluster
        CfnOutput(id="IsHITCluster", scope=self, value=str(self._condition_create_hit_substack()).lower())

    def _add_shared_storage_outputs(self):
        """Add the ids of the managed filesystem to the Stack Outputs."""
        for storage_type, storage_ids in self._storage_resource_ids.items():
            core.CfnOutput(
                scope=self,
                id="{0}Ids".format(storage_type.name),
                description="{0} Filesystem IDs".format(storage_type.name),
                value=",".join(storage_ids),
            )
