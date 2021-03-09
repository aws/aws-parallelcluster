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
import copy
import json
from hashlib import sha1

import pkg_resources
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_efs as efs
from aws_cdk import aws_fsx as fsx
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as awslambda
from aws_cdk import aws_route53 as route53
from aws_cdk import core

from common.aws.aws_api import AWSApi
from pcluster import utils
from pcluster.constants import OS_MAPPING
from pcluster.models.cluster_config import (
    ClusterBucket,
    ComputeType,
    CustomActionEvent,
    Ebs,
    SharedEbs,
    SharedEfs,
    SharedFsx,
    SharedStorageType,
    SlurmClusterConfig,
)
from pcluster.utils import get_availability_zone_of_subnet

# pylint: disable=too-many-lines


class ClusterCdkStack(core.Stack):
    """Create the CloudFormation stack template for the Cluster."""

    def __init__(
        self,
        scope: core.Construct,
        construct_id: str,
        cluster_config: SlurmClusterConfig,
        bucket: ClusterBucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self._cluster_config = cluster_config
        self._bucket = bucket

        self._init_mappings()
        self._add_resources()
        self._add_outputs()

    # -- Mappings ---------------------------------------------------------------------------------------------------- #

    def _init_mappings(self):
        self.packages_versions = {
            "parallelcluster": utils.get_installed_version(),
            "cookbook": "aws-parallelcluster-cookbook-2.10.1",
            "chef": "15.11.8",
            "berkshelf": "7.0.10",
            "ami": "dev",
        }

        # Storage filesystem Ids
        self._storage_resource_ids = {storage_type: [] for storage_type in SharedStorageType}
        self._storage_resource_options = {storage_type: "NONE" for storage_type in SharedStorageType}

    # -- Utility methods --------------------------------------------------------------------------------------------- #

    def _cluster_name(self):
        return core.Fn.select(1, core.Fn.split("parallelcluster-", self.stack_name))

    def _stack_unique_id(self):
        return core.Fn.select(2, core.Fn.split("/", self.stack_id))

    def _custom_chef_cookbook(self):
        return (
            self._cluster_config.dev_settings.cookbook.chef_cookbook
            if self._cluster_config.dev_settings
            and self._cluster_config.dev_settings.cookbook
            and self._cluster_config.dev_settings.cookbook.chef_cookbook
            else "NONE"
        )

    def _get_user_data_content(self, user_data_path: str):
        user_data_file_path = pkg_resources.resource_filename(__name__, user_data_path)
        with open(user_data_file_path, "r") as user_data_file:
            user_data_content = user_data_file.read()
        return user_data_content

    def _get_shared_storage_ids(self, storage_type: SharedStorageType):
        return (
            ",".join(self._storage_resource_ids[storage_type]) if self._storage_resource_ids[storage_type] else "NONE"
        )

    def _get_shared_storage_options(self, storage_type: SharedStorageType):
        default_storage_options = {
            SharedStorageType.EBS: "NONE,NONE,NONE,NONE,NONE",
            SharedStorageType.RAID: "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
            SharedStorageType.EFS: "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
            SharedStorageType.FSX: (
                "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE"
            ),
        }
        return (
            self._storage_resource_options[storage_type]
            if self._storage_resource_options[storage_type]
            else default_storage_options[storage_type]
        )

    def _get_block_device_mappings(self, node_config):
        # Default block device mapping
        block_device_mappings = []
        for _, (device_name_index, virtual_name_index) in enumerate(zip(list(map(chr, range(97, 121))), range(0, 24))):
            device_name = "/dev/xvdb{0}".format(device_name_index)
            virtual_name = "ephemeral{0}".format(virtual_name_index)
            block_device_mappings.append(
                ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(device_name=device_name, virtual_name=virtual_name)
            )

        # Root volume
        if node_config.storage and node_config.storage.root_volume:
            root_volume = copy.deepcopy(node_config.storage.root_volume)
        else:
            root_volume = Ebs()

        block_device_mappings.append(
            ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                device_name=OS_MAPPING[self._cluster_config.image.os]["root-device"],
                ebs=ec2.CfnLaunchTemplate.EbsProperty(
                    volume_size=root_volume.size,
                    volume_type=root_volume.volume_type,
                ),
            )
        )
        return block_device_mappings

    def _get_custom_tags(self):
        custom_tags = []
        if self._cluster_config.tags:
            custom_tags = [core.CfnTag(key=tag.key, value=tag.value) for tag in self._cluster_config.tags]
        return custom_tags

    def _create_hash_suffix(self, string_to_hash):
        return sha1(string_to_hash.encode("utf-8")).hexdigest()[:16].capitalize()

    def _get_extra_chef_attributes(self):
        return (
            self._cluster_config.dev_settings.cookbook.extra_chef_attributes
            if self._cluster_config.dev_settings
            and self._cluster_config.dev_settings.cookbook
            and self._cluster_config.dev_settings.cookbook.extra_chef_attributes
            else "{}"
        )

    def _get_default_instance_tags(self, node, node_type):
        return [
            core.CfnTag(key="Name", value=node_type),
            core.CfnTag(key="ClusterName", value=self._cluster_name()),
            core.CfnTag(key="Application", value=self.stack_name),
            core.CfnTag(key="aws-parallelcluster-node-type", value=node_type),
            core.CfnTag(
                key="aws-parallelcluster-attributes",
                value="{BaseOS}, {Scheduler}, {Version}, {Architecture}".format(
                    BaseOS=self._cluster_config.image.os,
                    Scheduler=self._cluster_config.scheduling.scheduler,
                    Version=utils.get_installed_version(),
                    Architecture=node.architecture,
                ),
            ),
            core.CfnTag(
                key="aws-parallelcluster-networking",
                value="EFA={0}".format("true" if node.efa and node.efa.enabled else "NONE"),
            ),
            core.CfnTag(
                key="aws-parallelcluster-filesystem",
                value="efs={efs}, multiebs={multiebs}, raid={raid}, fsx={fsx}".format(
                    efs=len(self._storage_resource_ids[SharedStorageType.EFS]),
                    multiebs=len(self._storage_resource_ids[SharedStorageType.EBS]),
                    raid=len(self._storage_resource_ids[SharedStorageType.RAID]),
                    fsx=len(self._storage_resource_ids[SharedStorageType.FSX]),
                ),
            ),
        ]

    def _get_default_volume_tags(self, node_type):
        return [
            core.CfnTag(key="ClusterName", value=self._cluster_name()),
            core.CfnTag(key="Application", value=self.stack_name),
            core.CfnTag(key="aws-parallelcluster-node-type", value=node_type),
        ]

    # -- Resources --------------------------------------------------------------------------------------------------- #

    def _add_resources(self):
        # CloudWatchLogsSubstack
        # TODO: inline cw-logs-substack

        # Head Node EC2 Iam Role
        self.head_node_iam_role = (
            self._add_root_iam_role()
            if self._condition_create_head_node_iam_role()
            else self._cluster_config.head_node.iam.roles.instance_role
        )
        # TODO split head node and queues roles

        # Root Instance Profile
        self.root_instance_profile = self._add_root_instance_profile()

        # ParallelCluster Policies
        if self._condition_create_head_node_iam_role():
            self._add_parallelcluster_policies()
            # TODO attach policies to each queue instance role

        # Slurm Policies
        if self._condition_add_slurm_iam_policies():
            self._add_slurm_policies()

        # S3 Access Policies
        if self._condition_create_s3_access_policies():
            self._add_s3_access_policies()

        # Head Node EIP
        if self._cluster_config.head_node.networking.assign_public_ip:
            self._head_eip = ec2.CfnEIP(scope=self, id="HeadNodeEIP", domain="vpc")

        # ParallelCluster managed security groups
        self._add_security_groups()

        # Head Node ENI
        self.head_eni = self._add_head_eni()

        # AdditionalCfnStack
        if self._cluster_config.additional_resources:
            core.CfnStack(scope=self, id="AdditionalCfnStack", template_url=self._cluster_config.additional_resources)

        # AWSBatchStack
        # TODO: inline resources

        # Cleanup Resources Lambda Function
        self.cleanup_resources_function = self._add_cleanup_resources_lambda()

        # CleanupResourcesS3BucketCustomResource
        self.cleanup_resources_bucket_custom_resource = self._add_cleanup_resources_bucket_custom_resource()

        # DynamoDB to store cluster states
        # ToDo: evaluate other approaches to store cluster states
        self._add_dynamo_db_table()

        # CloudWatchDashboardSubstack
        # TODO: inline resources

        if self._cluster_config.shared_storage:
            for storage in self._cluster_config.shared_storage:
                self._add_shared_storage(storage)

        # Compute Fleet
        if self._condition_is_slurm():
            self._add_slurm_compute_fleet()

        # Head Node
        self._add_head_node()

    def _add_cleanup_resources_lambda(self):

        cleanup_resources_lambda_execution_role = None
        if self._condition_create_lambda_iam_role():
            s3_policy_actions = ["s3:DeleteObject", "s3:DeleteObjectVersion", "s3:ListBucket", "s3:ListBucketVersions"]
            if self._bucket.remove_on_deletion:
                s3_policy_actions.append("s3:DeleteBucket")

            cleanup_resources_lambda_execution_role = iam.CfnRole(
                scope=self,
                id="CleanupResourcesFunctionExecutionRole",
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
                                    resources=[self.format_arn(service="logs", account="*", region="*", resource="*")],
                                    sid="CloudWatchLogsPolicy",
                                ),
                                iam.PolicyStatement(
                                    actions=s3_policy_actions,
                                    effect=iam.Effect.ALLOW,
                                    resources=[
                                        self.format_arn(
                                            service="s3", resource=self._bucket.name, region="", account=""
                                        ),
                                        self.format_arn(
                                            service="s3",
                                            resource=f"{self._bucket.name}/{self._bucket.artifact_directory}/*",
                                            region="",
                                            account="",
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

            if self._condition_is_slurm():
                cleanup_resources_lambda_execution_role.policies[0].policy_document.add_statements(
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

        return awslambda.CfnFunction(
            scope=self,
            id="CleanupResourcesFunction",
            function_name=f"pcluster-CleanupResources-{self._stack_unique_id()}",
            code=awslambda.CfnFunction.CodeProperty(
                s3_bucket=self._bucket.name,
                s3_key=f"{self._bucket.artifact_directory}/custom_resources_code/artifacts.zip",
            ),
            handler="cleanup_resources.handler",
            memory_size=128,
            role=cleanup_resources_lambda_execution_role.attr_arn
            if cleanup_resources_lambda_execution_role
            else self.format_arn(
                service="iam",
                region="",
                resource="role/{0}".format(self._cluster_config.iam.roles.custom_lambda_resources),
            ),
            runtime="python3.8",
            timeout=900,
        )

    def _add_head_eni(self):
        head_eni_groupset = []
        if self._cluster_config.head_node.networking.additional_security_groups:
            head_eni_groupset.extend(self._cluster_config.head_node.networking.additional_security_groups)
        if self._condition_create_head_security_group():
            head_eni_groupset.append(self._head_security_group.ref)
        elif self._cluster_config.head_node.networking.security_groups:
            head_eni_groupset.extend(self._cluster_config.head_node.networking.security_groups)
        head_eni = ec2.CfnNetworkInterface(
            scope=self,
            id="HeadNodeENI",
            description="AWS ParallelCluster head node interface",
            subnet_id=self._cluster_config.head_node.networking.subnet_id,
            source_dest_check=False,
            group_set=head_eni_groupset,
        )
        # AssociateEIP
        if self._cluster_config.head_node.networking.assign_public_ip:
            ec2.CfnEIPAssociation(
                scope=self,
                id="AssociateEIP",
                allocation_id=self._head_eip.attr_allocation_id,
                network_interface_id=head_eni.ref,
            )
        return head_eni

    def _add_security_groups(self):
        # Head Node Security Group
        if self._condition_create_head_security_group():
            self._head_security_group = self._add_head_security_group()
        # ComputeSecurityGroup
        if self._condition_create_compute_security_group():
            self._compute_security_group = self._add_compute_security_group()
        # Head Node Security Group Ingress
        # Access to head node from compute nodes
        if self._condition_create_head_security_group() and self._condition_create_compute_security_group():
            ec2.CfnSecurityGroupIngress(
                scope=self,
                id="HeadNodeSecurityGroupIngress",
                ip_protocol="-1",
                from_port=0,
                to_port=65535,
                source_security_group_id=self._compute_security_group.ref,
                group_id=self._head_security_group.ref,
            )
        if self._condition_create_compute_security_group():
            # ComputeSecurityGroupEgress
            # Access to other compute nodes from compute nodes
            compute_security_group_egress = ec2.CfnSecurityGroupEgress(
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
            ec2.CfnSecurityGroupEgress(
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
            ec2.CfnSecurityGroupIngress(
                scope=self,
                id="ComputeSecurityGroupIngress",
                ip_protocol="-1",
                from_port=0,
                to_port=65535,
                source_security_group_id=self._compute_security_group.ref,
                group_id=self._compute_security_group.ref,
            )

    def _add_compute_security_group(self):
        return ec2.CfnSecurityGroup(
            scope=self,
            id="ComputeSecurityGroup",
            group_description="Allow access to resources in subnets behind front",
            vpc_id=self._cluster_config.vpc_id,
            security_group_ingress=[
                # Access from master security group
                ec2.CfnSecurityGroup.IngressProperty(
                    source_security_group_id=self._head_security_group.ref,
                    ip_protocol="-1",
                    from_port=0,
                    to_port=65535,
                )
            ],
        )

    def _add_s3_access_policies(self):
        read_only_s3_resources = [
            s3_access.bucket_name for s3_access in self._cluster_config.iam.s3_access if s3_access.type == "READ_ONLY"
        ]
        read_write_s3_resources = [
            s3_access.bucket_name for s3_access in self._cluster_config.iam.s3_access if s3_access.type != "READ_ONLY"
        ]
        s3_access_policy = iam.CfnPolicy(
            scope=self,
            id="S3AccessPolicies",
            policy_document=iam.PolicyDocument(statements=[]),
            roles=[self.head_node_iam_role.ref],
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

    def _add_root_instance_profile(self):
        root_instance_profile_roles = [
            self.head_node_iam_role.ref if hasattr(self, "head_node_iam_role") else None,
            self._cluster_config.head_iam_role,
            self._cluster_config.compute_iam_role,
        ]
        return iam.CfnInstanceProfile(
            scope=self,
            id="RootInstanceProfile",
            roles=[role for role in root_instance_profile_roles if role is not None],
            path="/",
        )

    def _add_root_iam_role(self):
        return iam.CfnRole(
            scope=self,
            id="RootRole",
            managed_policy_arns=self._cluster_config.iam.additional_iam_policies if self._cluster_config.iam else None,
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
        )

    def _add_parallelcluster_policies(self):
        iam.CfnPolicy(
            scope=self,
            id="ParallelClusterPolicies",
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
                        resources=[self.format_arn(service="sqs", resource=self.stack_name)],
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
                        resources=[self.format_arn(service="dynamodb", resource=f"table/{self.stack_name}")],
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
                                resource=f"{self._bucket.name}/{self._bucket.artifact_directory}/batch/",
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
            roles=[self.head_node_iam_role.ref],
        )

    def _add_slurm_policies(self):
        iam.CfnPolicy(
            scope=self,
            id="ParallelClusterSlurmPolicies",
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
                        if self._bucket.remove_on_deletion
                        else ["s3:*"],
                        resources=[
                            self.format_arn(service="s3", resource=self._bucket.name, region="", account=""),
                            self.format_arn(
                                service="s3",
                                resource=f"{self._bucket.name}/{self._bucket.artifact_directory}/*",
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
                            self.format_arn(service="dynamodb", resource="table/{0}".format(self.stack_name)),
                            self.format_arn(service="dynamodb", resource="table/{0}/index/*".format(self.stack_name)),
                        ],
                    ),
                ]
            ),
            roles=[self.head_node_iam_role.ref],
        )

    def _add_head_security_group(self):
        head_security_group_ingress = [
            # SSH access
            ec2.CfnSecurityGroup.IngressProperty(
                ip_protocol="tcp",
                from_port=22,
                to_port=22,
                cidr_ip=self._cluster_config.head_node.ssh.allowed_ips,
            ),
        ]
        if self._cluster_config.head_node.dcv and self._cluster_config.head_node.dcv.enabled:
            head_security_group_ingress.append(
                # DCV access
                ec2.CfnSecurityGroup.IngressProperty(
                    ip_protocol="tcp",
                    from_port=self._cluster_config.head_node.dcv.port,
                    to_port=self._cluster_config.head_node.dcv.port,
                    cidr_ip=self._cluster_config.head_node.dcv.allowed_ips,
                )
            )
        return ec2.CfnSecurityGroup(
            scope=self,
            id="HeadNodeSecurityGroup",
            group_description="Enable access to the head node",
            vpc_id=self._cluster_config.vpc_id,
            security_group_ingress=head_security_group_ingress,
        )

    def _add_cleanup_resources_bucket_custom_resource(self):
        return core.CustomResource(
            scope=self,
            id="CleanupResourcesS3BucketCustomResource",
            service_token=self.cleanup_resources_function.attr_arn,
            properties={
                "ResourcesS3Bucket": self._bucket.name,
                "ArtifactS3RootDirectory": self._bucket.artifact_directory,
                "RemoveBucketOnDeletion": self._bucket.remove_on_deletion,
                "Action": "DELETE_S3_ARTIFACTS",
            },
        )

    def _add_shared_storage(self, storage):
        """Add specific Cfn Resources to map the shared storage and store the output filesystem id."""
        storage_ids_list = self._storage_resource_ids[storage.shared_storage_type]
        cfn_resource_id = "{0}{1}".format(storage.shared_storage_type.name, len(storage_ids_list))
        if storage.shared_storage_type == SharedStorageType.FSX:
            storage_ids_list.append(self._add_fsx_storage(cfn_resource_id, storage))
        elif storage.shared_storage_type == SharedStorageType.EBS:
            storage_ids_list.append(self._add_ebs_volume(cfn_resource_id, storage))
        elif storage.shared_storage_type == SharedStorageType.EFS:
            storage_ids_list.append(self._add_efs_storage(cfn_resource_id, storage))
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
                subnet_ids=self._cluster_config.compute_subnet_ids,
                security_group_ids=self._cluster_config.compute_security_groups,
            )
            fsx_id = fsx_resource.ref

        # [shared_dir,fsx_fs_id,storage_capacity,fsx_kms_key_id,imported_file_chunk_size,
        # export_path,import_path,weekly_maintenance_start_time,deployment_type,
        # per_unit_storage_throughput,daily_automatic_backup_start_time,
        # automatic_backup_retention_days,copy_tags_to_backups,fsx_backup_id,
        # auto_import_policy,storage_type,drive_cache_type]",
        self._storage_resource_options[shared_fsx.shared_storage_type] = ",".join(
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
                shared_fsx.storage_type or "NONE",
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
        compute_subnet_ids = self._cluster_config.compute_subnet_ids
        compute_node_sgs = self._cluster_config.compute_security_groups or [self._compute_security_group.ref]
        for subnet_id in compute_subnet_ids:
            self._add_efs_mount_target(
                id, efs_id, compute_node_sgs, subnet_id, checked_availability_zones, new_file_system
            )

        # Mount Target for Head Node
        head_node_sgs = self._cluster_config.head_node.networking.security_groups or [self._head_security_group.ref]
        self._add_efs_mount_target(
            id,
            efs_id,
            head_node_sgs,
            self._cluster_config.head_node.networking.subnet_id,
            checked_availability_zones,
            new_file_system,
        )

        # [shared_dir,efs_fs_id,performance_mode,efs_kms_key_id,provisioned_throughput,encrypted,
        # throughput_mode,exists_valid_head_node_mt,exists_valid_compute_mt]
        self._storage_resource_options[shared_efs.shared_storage_type] = ",".join(
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
        availability_zone = get_availability_zone_of_subnet(subnet_id)
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
            ebs_ids.append(self._add_cfn_volume(f"{id_prefix}Volume{index}", shared_ebs))

        # [shared_dir,raid_type,num_of_raid_volumes,volume_type,volume_size,volume_iops,encrypted,
        # ebs_kms_key_id,volume_throughput]
        self._storage_resource_options[shared_ebs.shared_storage_type] = ",".join(
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
        self._storage_resource_options[shared_ebs.shared_storage_type] += (
            f",{shared_ebs.mount_dir}"
            if self._storage_resource_options[shared_ebs.shared_storage_type]
            else f"{shared_ebs.mount_dir}"
        )

        return ebs_id

    def _add_cfn_volume(self, id: str, shared_ebs: SharedEbs):
        return ec2.CfnVolume(
            scope=self,
            id=id,
            availability_zone=self._cluster_config.head_node.networking.availability_zone,
            encrypted=shared_ebs.encrypted,
            iops=shared_ebs.iops,
            throughput=shared_ebs.throughput,
            kms_key_id=shared_ebs.kms_key_id,
            size=shared_ebs.size,
            snapshot_id=shared_ebs.snapshot_id,
            volume_type=shared_ebs.volume_type,
        ).ref

    def _add_dynamo_db_table(self):
        table = dynamodb.CfnTable(
            scope=self,
            id="DynamoDBTable",
            table_name=self.stack_name,
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
        self._dynamo_db_table = table

    def _add_head_node(self):
        head_node = self._cluster_config.head_node

        # LT security groups
        head_lt_security_groups = []
        if head_node.networking.security_groups:
            head_lt_security_groups.extend(head_node.networking.security_groups)
        if head_node.networking.additional_security_groups:
            head_lt_security_groups.extend(head_node.networking.additional_security_groups)
        if self._head_security_group:
            head_lt_security_groups.append(self._head_security_group.ref)

        # LT network interfaces
        head_lt_nw_interfaces = [
            ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                device_index=0,
                network_interface_id=self.head_eni.ref,
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
                block_device_mappings=self._get_block_device_mappings(head_node),
                key_name=head_node.ssh.key_name,
                network_interfaces=head_lt_nw_interfaces,
                image_id=self._cluster_config.ami_id,
                ebs_optimized=head_node.is_ebs_optimized,
                iam_instance_profile=ec2.CfnLaunchTemplate.IamInstanceProfileProperty(
                    name=self.root_instance_profile.ref
                ),
                user_data=core.Fn.base64(
                    core.Fn.sub(
                        self._get_user_data_content("../resources/head_node/user_data.sh"),
                        {
                            "YumProxy": head_node.networking.proxy if head_node.networking.proxy else "_none_",
                            "DnfProxy": head_node.networking.proxy if head_node.networking.proxy else "",
                            "AptProxy": head_node.networking.proxy if head_node.networking.proxy else "false",
                            "ProxyServer": head_node.networking.proxy if head_node.networking.proxy else "NONE",
                            "CustomChefCookbook": self._custom_chef_cookbook(),
                            "ParallelClusterVersion": self.packages_versions["parallelcluster"],
                            "CookbookVersion": self.packages_versions["cookbook"],
                            "ChefVersion": self.packages_versions["chef"],
                            "BerkshelfVersion": self.packages_versions["berkshelf"],
                            "IamRoleName": self.head_node_iam_role.ref,
                        },
                    )
                ),
                tag_specifications=[
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="instance",
                        tags=self._get_default_instance_tags(head_node, "Master") + self._get_custom_tags(),
                    ),
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="volume",
                        tags=self._get_default_volume_tags("Master") + self._get_custom_tags(),
                    ),
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
                    "stack_name": self.stack_name,
                    "enable_efa": "true" if head_node.efa and head_node.efa.enabled else "NONE",
                    "cfn_raid_vol_ids": self._get_shared_storage_ids(SharedStorageType.RAID),
                    "cfn_raid_parameters": self._get_shared_storage_options(SharedStorageType.RAID),
                    "cfn_disable_hyperthreading_manually": "true"
                    if self._condition_disable_hyperthreading_manually(head_node)
                    else "false",
                    "cfn_base_os": self._cluster_config.image.os,
                    "cfn_preinstall": pre_install_action.script if pre_install_action else "NONE",
                    "cfn_preinstall_args": pre_install_action.args if pre_install_action else "NONE",
                    "cfn_postinstall": post_install_action.script if pre_install_action else "NONE",
                    "cfn_postinstall_args": post_install_action.args if pre_install_action else "NONE",
                    "cfn_region": self.region,
                    "cfn_efs": self._get_shared_storage_ids(SharedStorageType.EFS),
                    "cfn_efs_shared_dir": self._get_shared_storage_options(SharedStorageType.EFS),  # FIXME
                    "cfn_fsx_fs_id": self._get_shared_storage_ids(SharedStorageType.FSX),
                    "cfn_fsx_options": self._get_shared_storage_options(SharedStorageType.FSX),
                    "cfn_volume": self._get_shared_storage_ids(SharedStorageType.EBS),
                    "cfn_scheduler": self._cluster_config.scheduling.scheduler,
                    "cfn_encrypted_ephemeral": "true"
                    if head_node.storage
                    and head_node.storage.ephemeral_volume
                    and head_node.storage.ephemeral_volume.encrypted
                    else "NONE",
                    "cfn_ephemeral_dir": head_node.storage.ephemeral_volume.mount_dir
                    if head_node.storage and head_node.storage.ephemeral_volume
                    else "/scratch",
                    "cfn_shared_dir": self._get_shared_storage_options(SharedStorageType.EBS),
                    "cfn_proxy": head_node.networking.proxy if head_node.networking.proxy else "NONE",
                    "cfn_dns_domain": "" if self._condition_disable_cluster_dns() else self.cluster_hosted_zone.name,
                    "cfn_hosted_zone": ""
                    if self._condition_disable_cluster_dns()
                    else self.cluster_hosted_zone.attr_id,
                    "cfn_node_type": "MasterServer",  # FIXME
                    "cfn_cluster_user": OS_MAPPING[self._cluster_config.image.os]["user"],
                    "cfn_ddb_table": self._dynamo_db_table.ref,
                    "dcv_enabled": head_node.dcv.enabled if head_node.dcv else "false",
                    "dcv_port": head_node.dcv.port if head_node.dcv else "NONE",
                    "enable_intel_hpc_platform": "true" if self._condition_enable_intel_hpc_platform() else "false",
                    "cfn_cluster_cw_logging_enabled": "true" if self._condition_cw_logging_enabled() else "false",
                    "cluster_s3_bucket": self._bucket.name,
                    "cluster_config_s3_key": f"{self._bucket.artifact_directory}/configs/cluster-config.yaml",
                    "cluster_config_version": self._cluster_config.config_version,
                },
                "run_list": f"recipe[aws-parallelcluster::{self._cluster_config.scheduling.scheduler}_config]",
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
                        "content": self._get_extra_chef_attributes(),
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
                                "StackName": self.stack_name,
                                "Region": self.region,
                                "IamRoleName": self.head_node_iam_role.ref,
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
                                "IamRoleName": self.head_node_iam_role.ref,
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
        self.head_node_instance = ec2.CfnInstance(
            self,
            id="MasterServer",  # FIXME
            launch_template=ec2.CfnInstance.LaunchTemplateSpecificationProperty(
                launch_template_id=head_node_launch_template.ref,
                version=head_node_launch_template.attr_latest_version_number,
            ),
        )
        self.head_node_instance.cfn_options.creation_policy = core.CfnCreationPolicy(
            resource_signal=core.CfnResourceSignal(count=1, timeout="PT30M")
        )

    def _add_slurm_compute_fleet(self):

        self.cluster_hosted_zone = None
        if not self._condition_disable_cluster_dns():
            self.cluster_hosted_zone = self._add_private_hosted_zone()

        self._add_update_waiter_lambda()

        for queue in self._cluster_config.scheduling.queues:

            # LT security groups
            queue_lt_security_groups = []
            if queue.networking.security_groups:
                queue_lt_security_groups.extend(queue.networking.security_groups)
            if queue.networking.additional_security_groups:
                queue_lt_security_groups.extend(queue.networking.additional_security_groups)
            if self._compute_security_group:
                queue_lt_security_groups.append(self._compute_security_group.ref)

            queue_placement_group = None
            if queue.networking.placement_group and queue.networking.placement_group.enabled:
                if queue.networking.placement_group.id:
                    queue_placement_group = queue.networking.placement_group.id
                else:
                    # Create Placement Group
                    queue_placement_group = ec2.CfnPlacementGroup(
                        scope=self, id=f"PlacementGroup{self._create_hash_suffix(queue.name)}", strategy="cluster"
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
            service_token=self.cleanup_resources_function.attr_arn,
            properties={"StackName": self.stack_name, "Action": "TERMINATE_EC2_INSTANCES"},
        )
        # TODO: add depends_on resources from CloudWatchLogsSubstack and ComputeFleetHitSubstack?
        # terminate_compute_fleet_custom_resource.add_depends_on()

        core.CfnOutput(
            scope=self,
            id="ConfigVersion",
            description="Version of the config used to generate the stack",
            value=self._cluster_config.config_version,
        )

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
            id=f"ComputeServerLaunchTemplate{self._create_hash_suffix(queue.name + instance_type)}",
            launch_template_name=f"{self._cluster_name()}-{queue.name}-{instance_type}",
            launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
                instance_type=instance_type,
                cpu_options=ec2.CfnLaunchTemplate.CpuOptionsProperty(
                    core_count=compute_resource.vcpus, threads_per_core=1
                )
                if compute_resource.pass_cpu_options_in_launch_template
                else None,
                block_device_mappings=self._get_block_device_mappings(queue),
                # key_name=,
                network_interfaces=compute_lt_nw_interfaces,
                placement=queue_placement_group,
                image_id=self._cluster_config.ami_id,
                ebs_optimized=compute_resource.is_ebs_optimized,
                iam_instance_profile=ec2.CfnLaunchTemplate.IamInstanceProfileProperty(
                    name=self.root_instance_profile.ref
                ),
                instance_market_options=instance_market_options,
                user_data=core.Fn.base64(
                    core.Fn.sub(
                        self._get_user_data_content("../resources/compute_node/user_data.sh"),
                        {
                            "YumProxy": queue.networking.proxy if queue.networking.proxy else "_none_",
                            "DnfProxy": queue.networking.proxy if queue.networking.proxy else "",
                            "AptProxy": queue.networking.proxy if queue.networking.proxy else "false",
                            "ProxyServer": queue.networking.proxy if queue.networking.proxy else "NONE",
                            "CustomChefCookbook": self._custom_chef_cookbook(),
                            "ParallelClusterVersion": self.packages_versions["parallelcluster"],
                            "CookbookVersion": self.packages_versions["cookbook"],
                            "ChefVersion": self.packages_versions["chef"],
                            "BerkshelfVersion": self.packages_versions["berkshelf"],
                            "IamRoleName": self.head_node_iam_role.ref,  # TODO split roles
                            "EnableEfa": "efa" if compute_resource.efa and compute_resource.efa.enabled else "NONE",
                            "RAIDOptions": self._get_shared_storage_options(SharedStorageType.RAID),
                            "DisableHyperThreadingManually": "true"
                            if self._condition_disable_hyperthreading_manually(compute_resource)
                            else "false",
                            "BaseOS": self._cluster_config.image.os,
                            "PreInstallScript": queue_pre_install_action.script if queue_pre_install_action else "NONE",
                            "PreInstallArgs": queue_pre_install_action.args if queue_pre_install_action else "NONE",
                            "PostInstallScript": queue_post_install_action.script
                            if queue_pre_install_action
                            else "NONE",
                            "PostInstallArgs": queue_post_install_action.args if queue_pre_install_action else "NONE",
                            "EFSId": self._get_shared_storage_ids(SharedStorageType.EFS),
                            "EFSOptions": self._get_shared_storage_options(SharedStorageType.EFS),  # FIXME
                            "FSXId": self._get_shared_storage_ids(SharedStorageType.FSX),
                            "FSXOptions": self._get_shared_storage_options(SharedStorageType.FSX),
                            "Scheduler": self._cluster_config.scheduling.scheduler,
                            "EncryptedEphemeral": "true"
                            if queue.storage
                            and queue.storage.ephemeral_volume
                            and queue.storage.ephemeral_volume.encrypted
                            else "NONE",
                            "EphemeralDir": queue.storage.ephemeral_volume.mount_dir
                            if queue.storage and queue.storage.ephemeral_volume
                            else "/scratch",
                            "EbsSharedDirs": self._get_shared_storage_options(SharedStorageType.EBS),
                            "ClusterDNSDomain": ""
                            if self._condition_disable_cluster_dns()
                            else self.cluster_hosted_zone.name,
                            "ClusterHostedZone": ""
                            if self._condition_disable_cluster_dns()
                            else self.cluster_hosted_zone.attr_id,
                            "OSUser": OS_MAPPING[self._cluster_config.image.os]["user"],
                            "DynamoDBTable": self._dynamo_db_table.ref,
                            "IntelHPCPlatform": "true" if self._condition_enable_intel_hpc_platform() else "false",
                            "CWLoggingEnabled": "true" if self._condition_cw_logging_enabled() else "false",
                            "QueueName": queue.name,
                            "EnableEfaGdr": "compute"
                            if compute_resource.efa and compute_resource.efa.gdr_support
                            else "NONE",
                            "ExtraJson": self._get_extra_chef_attributes(),
                        },
                    )
                ),
                monitoring=ec2.CfnLaunchTemplate.MonitoringProperty(enabled=False),
                tag_specifications=[
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="instance",
                        tags=self._get_default_instance_tags(compute_resource, "Compute")
                        + [core.CfnTag(key="QueueName", value=queue.name)]
                        + self._get_custom_tags(),
                    ),
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="volume",
                        tags=self._get_default_volume_tags("Compute")
                        + [core.CfnTag(key="QueueName", value=queue.name)]
                        + self._get_custom_tags(),
                    ),
                ],
            ),
        )

    def _add_private_hosted_zone(self):
        cluster_hosted_zone = route53.CfnHostedZone(
            self,
            id="Route53HostedZone",
            name=f"{self._cluster_name()}.pcluster",
            vpcs=[route53.CfnHostedZone.VPCProperty(vpc_id=self._cluster_config.vpc_id, vpc_region=self.region)],
        )

        if self._condition_create_head_node_iam_role():
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
                                self.format_arn(
                                    service="route53",
                                    region="",
                                    account="",
                                    resource=f"hostedzone/{cluster_hosted_zone.attr_id}",
                                ),
                            ],
                        ),
                    ]
                ),
                roles=[self.head_node_iam_role.ref],  # TODO use compute fleet role
            )

        cleanup_route53_lambda_execution_role = None
        if self._condition_create_lambda_iam_role():
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
                                    resources=[self.format_arn(service="logs", account="*", region="*", resource="*")],
                                    sid="CloudWatchLogsPolicy",
                                ),
                                iam.PolicyStatement(
                                    actions=["route53:ListResourceRecordSets", "route53:ChangeResourceRecordSets"],
                                    effect=iam.Effect.ALLOW,
                                    resources=[
                                        self.format_arn(
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
                s3_bucket=self._bucket.name,
                s3_key=f"{self._bucket.artifact_directory}/custom_resources_code/artifacts.zip",
            ),
            handler="cleanup_resources.handler",
            memory_size=128,
            role=cleanup_route53_lambda_execution_role.attr_arn
            if cleanup_route53_lambda_execution_role
            else self.format_arn(
                service="iam",
                region="",
                account=self.account,
                resource="role/{0}".format(self._cluster_config.iam.roles.custom_lambda_resources),
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
        if self._condition_create_lambda_iam_role():
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
                                    resources=[self.format_arn(service="logs", account="*", region="*", resource="*")],
                                    sid="CloudWatchLogsPolicy",
                                ),
                                iam.PolicyStatement(
                                    actions=["dynamodb:GetItem", "dynamodb:PutItem"],
                                    effect=iam.Effect.ALLOW,
                                    resources=[
                                        self.format_arn(
                                            service="dynamodb",
                                            account=self.account,
                                            resource=f"table/{self._dynamo_db_table.ref}",
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
                s3_bucket=self._bucket.name,
                s3_key=f"{self._bucket.artifact_directory}/custom_resources_code/artifacts.zip",
            ),
            handler="wait_for_update.handler",
            memory_size=128,
            role=update_waiter_lambda_execution_role.attr_arn
            if update_waiter_lambda_execution_role
            else self.format_arn(
                service="iam",
                region="",
                account=self.account,
                resource="role/{0}".format(self._cluster_config.iam.roles.custom_lambda_resources),
            ),
            runtime="python3.8",
            timeout=900,
        )

        core.CustomResource(
            self,
            "UpdateWaiterCustomResource",
            service_token=update_waiter_lambda.attr_arn,
            properties={
                "ConfigVersion": self._cluster_config.config_version,
                "DynamoDBTable": self._dynamo_db_table.ref,
            },
        )

        core.CfnOutput(scope=self, id="UpdateWaiterFunctionArn", value=update_waiter_lambda.attr_arn)

    # -- Conditions -------------------------------------------------------------------------------------------------- #

    def _condition_create_head_node_iam_role(self):
        """Head node role is created if head instance role is not specified."""
        head_node = self._cluster_config.head_node
        return not head_node.iam or not head_node.iam.roles or not head_node.iam.roles.instance_role

    def _condition_create_compute_iam_role(self, queue):
        """Compute Iam role is created if queue instance role is not specified."""
        return not queue.iam or not queue.iam.roles or not queue.iam.roles.instance_role

    def _condition_disable_hyperthreading_manually(self, node_config):
        return (
            node_config.disable_simultaneous_multithreading
            and not node_config.disable_simultaneous_multithreading_via_cpu_options
        )

    def _condition_create_lambda_iam_role(self):
        return (
            not self._cluster_config.iam
            or not self._cluster_config.iam.roles
            or not self._cluster_config.iam.roles.custom_lambda_resources
            or self._cluster_config.iam.roles.get_param("custom_lambda_resources").implied
        )

    def _condition_create_s3_access_policies(self):
        return self._cluster_config.iam and self._cluster_config.iam.s3_access

    def _condition_add_slurm_iam_policies(self):
        return self._condition_create_head_node_iam_role() and self._condition_is_slurm()

    def _condition_create_compute_security_group(self):
        # Compute security group must be created if at list one queue's networking does not specify security groups
        condition = False
        for queue in self._cluster_config.scheduling.queues:
            if not queue.networking.security_groups:
                condition = True
        return condition

    def _condition_create_head_security_group(self):
        return not self._cluster_config.head_node.networking.security_groups

    def _condition_is_slurm(self):
        return self._cluster_config.scheduling.scheduler == "slurm"

    def _condition_cw_logging_enabled(self):
        return (
            self._cluster_config.monitoring.logs.cloud_watch.enabled
            if self._cluster_config.monitoring
            and self._cluster_config.monitoring.logs
            and self._cluster_config.monitoring.logs.cloud_watch
            else False
        )

    def _condition_enable_intel_hpc_platform(self):
        return (
            self._cluster_config.additional_packages.intel_select_solutions.install_intel_software
            if self._cluster_config.additional_packages
            and self._cluster_config.additional_packages.intel_select_solutions
            else False
        )

    def _condition_disable_cluster_dns(self):
        return (
            self._cluster_config.scheduling.settings
            and self._cluster_config.scheduling.settings.dns
            and self._cluster_config.scheduling.settings.dns.disable_managed_dns
        )

    # -- Outputs ----------------------------------------------------------------------------------------------------- #

    def _add_outputs(self):
        # Storage filesystem Ids
        self._add_shared_storage_outputs()

        # ClusterUser
        core.CfnOutput(
            scope=self,
            id="ClusterUser",
            description="Username to login to head node",
            value=OS_MAPPING[self._cluster_config.image.os]["user"],
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
            value=self._bucket.name,
        )

        # ArtifactS3RootDirectory
        core.CfnOutput(
            scope=self,
            id="ArtifactS3RootDirectory",
            description="Root directory in S3 bucket where cluster artifacts are stored",
            value=self._bucket.artifact_directory,
        )

        # BatchComputeEnvironmentArn
        # BatchJobQueueArn
        # BatchJobDefinitionArn
        # BatchJobDefinitionMnpArn
        # BatchUserRole
        # TODO: take values from Batch resources

        core.CfnOutput(id="Scheduler", scope=self, value=self._cluster_config.scheduling.scheduler)

    def _add_shared_storage_outputs(self):
        """Add the ids of the managed filesystem to the Stack Outputs."""
        for storage_type, storage_ids in self._storage_resource_ids.items():
            core.CfnOutput(
                scope=self,
                id="{0}Ids".format(storage_type.name),
                description="{0} Filesystem IDs".format(storage_type.name),
                value=",".join(storage_ids),
            )
