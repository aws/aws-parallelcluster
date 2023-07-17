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

# pylint: disable=too-many-lines

import collections.abc

#
# This module contains all the classes required to convert a Cluster into a CFN template by using CDK.
#
import json
from collections import defaultdict, namedtuple
from datetime import datetime
from typing import Union

from aws_cdk import aws_cloudformation as cfn
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_dynamodb as dynamomdb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_efs as efs
from aws_cdk import aws_fsx as fsx
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk.core import (
    CfnDeletionPolicy,
    CfnOutput,
    CfnParameter,
    CfnStack,
    CfnTag,
    Construct,
    CustomResource,
    Duration,
    Fn,
    Stack,
    Tags,
)

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from pcluster.config.cluster_config import (
    AwsBatchClusterConfig,
    BaseSharedFsx,
    ExistingFsxFileCache,
    ExistingFsxOntap,
    ExistingFsxOpenZfs,
    SharedEbs,
    SharedEfs,
    SharedFsxLustre,
    SharedStorageType,
    SlurmClusterConfig,
)
from pcluster.constants import (
    ALL_PORTS_RANGE,
    CW_ALARM_DATAPOINTS_TO_ALARM_DEFAULT,
    CW_ALARM_EVALUATION_PERIODS_DEFAULT,
    CW_ALARM_PERCENT_THRESHOLD_DEFAULT,
    CW_ALARM_PERIOD_DEFAULT,
    CW_LOG_GROUP_NAME_PREFIX,
    CW_LOGS_CFN_PARAM_NAME,
    DEFAULT_EPHEMERAL_DIR,
    EFS_PORT,
    FSX_PORTS,
    LUSTRE,
    NFS_PORT,
    NODE_BOOTSTRAP_TIMEOUT,
    OS_MAPPING,
    PCLUSTER_DYNAMODB_PREFIX,
    PCLUSTER_S3_ARTIFACTS_DICT,
    SLURM_PORTS_RANGE,
)
from pcluster.models.s3_bucket import S3Bucket
from pcluster.templates.awsbatch_builder import AwsBatchConstruct
from pcluster.templates.cdk_builder_utils import (
    CdkLaunchTemplateBuilder,
    HeadNodeIamResources,
    PclusterLambdaConstruct,
    add_lambda_cfn_role,
    apply_permissions_boundary,
    convert_deletion_policy,
    create_hash_suffix,
    get_cloud_watch_logs_policy_statement,
    get_cloud_watch_logs_retention_days,
    get_common_user_data_env,
    get_custom_tags,
    get_default_instance_tags,
    get_default_volume_tags,
    get_directory_service_dna_json_for_head_node,
    get_lambda_log_group_prefix,
    get_log_group_deletion_policy,
    get_shared_storage_ids_by_type,
    get_slurm_specific_dna_json_for_head_node,
    get_user_data_content,
    to_comma_separated_string,
)
from pcluster.templates.compute_fleet_stack import ComputeFleetConstruct
from pcluster.templates.cw_dashboard_builder import CWDashboardConstruct
from pcluster.templates.login_nodes_stack import LoginNodesStack
from pcluster.templates.slurm_builder import SlurmConstruct
from pcluster.utils import get_attr, get_http_tokens_setting, get_service_endpoint

StorageInfo = namedtuple("StorageInfo", ["id", "config"])


class ClusterCdkStack:
    """Create the CloudFormation stack template for the Cluster."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        stack_name: str,
        cluster_config: Union[SlurmClusterConfig, AwsBatchClusterConfig],
        bucket: S3Bucket,
        log_group_name=None,
        **kwargs,
    ) -> None:
        self.stack = Stack(scope=scope, id=construct_id, **kwargs)
        self._stack_name = stack_name
        self._launch_template_builder = CdkLaunchTemplateBuilder()
        self.config = cluster_config
        self.bucket = bucket
        self.timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        if self.config.is_cw_logging_enabled:
            if log_group_name:
                # pcluster update keep the log group,
                # It has to be passed in order to avoid the change of log group name because of the suffix.
                self.log_group_name = log_group_name
            else:
                # pcluster create create a log group with timestamp suffix
                timestamp = f"{datetime.utcnow().strftime('%Y%m%d%H%M')}"
                self.log_group_name = f"{CW_LOG_GROUP_NAME_PREFIX}{self.stack.stack_name}-{timestamp}"

        self.shared_storage_infos = {storage_type: [] for storage_type in SharedStorageType}
        self.shared_storage_mount_dirs = {storage_type: [] for storage_type in SharedStorageType}
        self.shared_storage_attributes = {storage_type: defaultdict(list) for storage_type in SharedStorageType}

        self._add_parameters()
        self._add_resources()
        self._add_outputs()

        try:
            apply_permissions_boundary(cluster_config.iam.permissions_boundary, self.stack)
        except AttributeError:
            pass

    # -- Utility methods --------------------------------------------------------------------------------------------- #

    def _stack_unique_id(self):
        return Fn.select(2, Fn.split("/", self.stack.stack_id))

    def _build_resource_path(self):
        return self.stack.stack_id

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

    def _get_login_security_groups(self):
        """Return list of security groups to be used for the login nodes, created by us AND provided by the user."""
        login_security_groups = (
            [
                security_group
                for pool in self.config.login_nodes.pools
                if pool.networking.security_groups
                for security_group in pool.networking.security_groups
            ]
            if isinstance(self.config, SlurmClusterConfig) and self.config.login_nodes
            else []
        )

        if self._login_security_group:
            login_security_groups.append(self._login_security_group.ref)

        return login_security_groups

    # -- Parameters -------------------------------------------------------------------------------------------------- #

    def _add_parameters(self):
        CfnParameter(
            self.stack,
            "ClusterUser",
            description="Username to login to head node",
            default=OS_MAPPING[self.config.image.os]["user"],
        )
        CfnParameter(
            self.stack,
            "ResourcesS3Bucket",
            description="S3 user bucket where AWS ParallelCluster resources are stored",
            default=self.bucket.name,
        )
        CfnParameter(
            self.stack,
            "ArtifactS3RootDirectory",
            description="Root directory in S3 bucket where cluster artifacts are stored",
            default=self.bucket.artifact_directory,
        )
        CfnParameter(self.stack, "Scheduler", default=self.config.scheduling.scheduler)

        try:
            CfnParameter(self.stack, "OfficialAmi", default=self.config.official_ami)
        except AWSClientError:
            # This might happen if there is no official AMI
            # and custom AMIs are defined for the head node and compute nodes
            pass

        CfnParameter(
            self.stack,
            "ConfigVersion",
            description="Version of the original config used to generate the stack",
            default=self.config.original_config_version,
        )
        if self.config.is_cw_logging_enabled:
            CfnParameter(
                self.stack,
                CW_LOGS_CFN_PARAM_NAME,
                description="CloudWatch Log Group associated to the cluster",
                default=self.log_group_name,
            )

    # -- Resources --------------------------------------------------------------------------------------------------- #

    def _add_resources(self):
        # Cloud Watch Logs
        self.log_group = None
        if self.config.is_cw_logging_enabled:
            self.log_group = self._add_cluster_log_group()

        # Managed security groups
        (
            self._head_security_group,
            self._compute_security_group,
            self._login_security_group,
        ) = self._add_security_groups()
        # Head Node ENI
        self._head_eni = self._add_head_eni()

        if self.config.shared_storage:
            for storage in self.config.shared_storage:
                self._add_shared_storage(storage)

        self._add_iam_resources()

        # Additional Cfn Stack
        if self.config.additional_resources:
            CfnStack(self.stack, "AdditionalCfnStack", template_url=self.config.additional_resources)

        # Cleanup Resources Lambda Function
        cleanup_lambda_role, cleanup_lambda = self._add_cleanup_resources_lambda()

        self._add_fleet_and_scheduler_resources(cleanup_lambda, cleanup_lambda_role)

        # Wait condition
        self.wait_condition, self.wait_condition_handle = self._add_wait_condition()

        # Head Node
        self.head_node_instance = self._add_head_node()
        # Add a dependency to the cleanup Route53 resource, so that Route53 Hosted Zone is cleaned after node is deleted
        if self._condition_is_slurm() and hasattr(self.scheduler_resources, "cleanup_route53_custom_resource"):
            self.head_node_instance.add_depends_on(self.scheduler_resources.cleanup_route53_custom_resource)

        # Initialize Login Nodes
        self._add_login_nodes_resources()

        # AWS Batch related resources
        if self._condition_is_batch():
            self.scheduler_resources = AwsBatchConstruct(
                scope=self.stack,
                id="AwsBatch",
                stack_name=self._stack_name,
                cluster_config=self.config,
                bucket=self.bucket,
                create_lambda_roles=self._condition_create_lambda_iam_role(),
                compute_security_group=self._compute_security_group,
                shared_storage_infos=self.shared_storage_infos,
                shared_storage_mount_dirs=self.shared_storage_mount_dirs,
                head_node_instance=self.head_node_instance,
                managed_head_node_instance_role=self._managed_head_node_instance_role,  # None if provided by the user
            )

        # CloudWatch Dashboard
        if self.config.is_cw_dashboard_enabled:
            self.cloudwatch_dashboard = CWDashboardConstruct(
                scope=self.stack,
                id="PclusterDashboard",
                stack_name=self.stack.stack_name,
                cluster_config=self.config,
                head_node_instance=self.head_node_instance,
                shared_storage_infos=self.shared_storage_infos,
                cw_log_group_name=self.log_group.log_group_name if self.config.is_cw_logging_enabled else None,
                cw_log_group=self.log_group,
            )

            self._add_alarms()

    def _add_alarms(self):
        self.alarms = []

        metrics_for_alarms = {
            "Mem": cloudwatch.Metric(
                namespace="CWAgent",
                metric_name="mem_used_percent",
                dimensions_map={"InstanceId": self.head_node_instance.ref},
                statistic="Maximum",
                period=Duration.seconds(CW_ALARM_PERIOD_DEFAULT),
            ),
            "Disk": cloudwatch.Metric(
                namespace="CWAgent",
                metric_name="disk_used_percent",
                dimensions_map={"InstanceId": self.head_node_instance.ref, "path": "/"},
                statistic="Maximum",
                period=Duration.seconds(CW_ALARM_PERIOD_DEFAULT),
            ),
        }

        for metric_key, metric in metrics_for_alarms.items():
            alarm_id = f"HeadNode{metric_key}Alarm"
            alarm_name = f"{self.stack.stack_name}_{metric_key}Alarm_HeadNode"
            self.alarms.append(
                cloudwatch.Alarm(
                    scope=self.stack,
                    id=alarm_id,
                    metric=metric,
                    evaluation_periods=CW_ALARM_EVALUATION_PERIODS_DEFAULT,
                    threshold=CW_ALARM_PERCENT_THRESHOLD_DEFAULT,
                    alarm_name=alarm_name,
                    comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                    datapoints_to_alarm=CW_ALARM_DATAPOINTS_TO_ALARM_DEFAULT,
                )
            )

    def _add_iam_resources(self):
        head_node_iam_resources = HeadNodeIamResources(
            self.stack,
            "HeadNodeIamResources",
            self.config,
            self.config.head_node,
            self.shared_storage_infos,
            "HeadNode",
            self.bucket,
        )
        self._head_node_instance_profile = head_node_iam_resources.instance_profile
        self._managed_head_node_instance_role = head_node_iam_resources.instance_role

    def _add_cluster_log_group(self):
        log_group = logs.CfnLogGroup(
            self.stack,
            "CloudWatchLogGroup",
            log_group_name=self.log_group_name,
            retention_in_days=get_cloud_watch_logs_retention_days(self.config),
        )
        log_group.cfn_options.deletion_policy = get_log_group_deletion_policy(self.config)
        return log_group

    def _add_fleet_and_scheduler_resources(self, cleanup_lambda, cleanup_lambda_role):
        # Compute Fleet and scheduler related resources
        self.scheduler_resources = None
        if self._condition_is_slurm():
            self.scheduler_resources = SlurmConstruct(
                scope=self.stack,
                id="Slurm",
                stack_name=self._stack_name,
                cluster_config=self.config,
                bucket=self.bucket,
                managed_head_node_instance_role=self._managed_head_node_instance_role,
                cleanup_lambda_role=cleanup_lambda_role,  # None if provided by the user
                cleanup_lambda=cleanup_lambda,
            )
        if not self._condition_is_batch():
            _dynamodb_table_status = dynamomdb.CfnTable(
                self.stack,
                "DynamoDBTable",
                table_name=PCLUSTER_DYNAMODB_PREFIX + self.stack.stack_name,
                attribute_definitions=[
                    dynamomdb.CfnTable.AttributeDefinitionProperty(attribute_name="Id", attribute_type="S"),
                ],
                key_schema=[dynamomdb.CfnTable.KeySchemaProperty(attribute_name="Id", key_type="HASH")],
                billing_mode="PAY_PER_REQUEST",
            )
            _dynamodb_table_status.cfn_options.update_replace_policy = CfnDeletionPolicy.RETAIN
            _dynamodb_table_status.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE
            self.dynamodb_table_status = _dynamodb_table_status
        self.compute_fleet_resources = None
        if not self._condition_is_batch():
            self.compute_fleet_resources = ComputeFleetConstruct(
                scope=self.stack,
                id="ComputeFleet",
                cluster_config=self.config,
                log_group=self.log_group,
                cleanup_lambda=cleanup_lambda,
                cleanup_lambda_role=cleanup_lambda_role,
                compute_security_group=self._compute_security_group,
                shared_storage_infos=self.shared_storage_infos,
                shared_storage_mount_dirs=self.shared_storage_mount_dirs,
                shared_storage_attributes=self.shared_storage_attributes,
                cluster_hosted_zone=self.scheduler_resources.cluster_hosted_zone if self.scheduler_resources else None,
                dynamodb_table=self.scheduler_resources.dynamodb_table if self.scheduler_resources else None,
                head_eni=self._head_eni,
                slurm_construct=self.scheduler_resources,
            )

    def _add_login_nodes_resources(self):
        """Add Login Nodes related resources."""
        self.login_nodes_stack = None
        if self._condition_is_slurm() and self.config.login_nodes:
            self.login_nodes_stack = LoginNodesStack(
                scope=self.stack,
                id="LoginNodes",
                cluster_config=self.config,
                log_group=self.log_group,
                shared_storage_infos=self.shared_storage_infos,
                shared_storage_mount_dirs=self.shared_storage_mount_dirs,
                shared_storage_attributes=self.shared_storage_attributes,
                login_security_group=self._login_security_group,
                head_eni=self._head_eni,
                cluster_hosted_zone=self.scheduler_resources.cluster_hosted_zone if self.scheduler_resources else None,
            )
            Tags.of(self.login_nodes_stack).add(
                # This approach works since by design we have now only one pool.
                # We should fix this if we want to add more than a login nodes pool per cluster.
                "parallelcluster:login-nodes-pool",
                self.config.login_nodes.pools[0].name,
            )
            # Add dependency on the Head Node construct
            self.login_nodes_stack.node.add_dependency(self.head_node_instance)

    def _add_cleanup_resources_lambda(self):
        """Create Lambda cleanup resources function and its role."""
        cleanup_resources_lambda_role = None
        if self._condition_create_lambda_iam_role():
            s3_policy_actions = ["s3:DeleteObject", "s3:DeleteObjectVersion", "s3:ListBucket", "s3:ListBucketVersions"]

            cleanup_resources_lambda_role = add_lambda_cfn_role(
                scope=self.stack,
                config=self.config,
                function_id="CleanupResources",
                statements=[
                    iam.PolicyStatement(
                        actions=s3_policy_actions,
                        effect=iam.Effect.ALLOW,
                        resources=[
                            self.stack.format_arn(service="s3", resource=self.bucket.name, region="", account=""),
                            self.stack.format_arn(
                                service="s3",
                                resource=f"{self.bucket.name}/{self.bucket.artifact_directory}/*",
                                region="",
                                account="",
                            ),
                        ],
                        sid="S3BucketPolicy",
                    ),
                    get_cloud_watch_logs_policy_statement(
                        resource=self.stack.format_arn(
                            service="logs",
                            account=self.stack.account,
                            region=self.stack.region,
                            resource=get_lambda_log_group_prefix("CleanupResources-*"),
                        )
                    ),
                ],
                has_vpc_config=self.config.lambda_functions_vpc_config,
            )

        cleanup_resources_lambda = PclusterLambdaConstruct(
            scope=self.stack,
            id="CleanupResourcesFunctionConstruct",
            function_id="CleanupResources",
            bucket=self.bucket,
            config=self.config,
            execution_role=cleanup_resources_lambda_role.attr_arn
            if cleanup_resources_lambda_role
            else self.config.iam.roles.lambda_functions_role,
            handler_func="cleanup_resources",
        ).lambda_func

        CustomResource(
            self.stack,
            "CleanupResourcesS3BucketCustomResource",
            service_token=cleanup_resources_lambda.attr_arn,
            properties={
                "ResourcesS3Bucket": self.bucket.name,
                "ArtifactS3RootDirectory": self.bucket.artifact_directory,
                "Action": "DELETE_S3_ARTIFACTS",
            },
        )

        return cleanup_resources_lambda_role, cleanup_resources_lambda

    def _add_head_eni(self):
        """Create Head Node Elastic Network Interface."""
        head_eni_group_set = self._get_head_node_security_groups_full()

        head_eni = ec2.CfnNetworkInterface(
            self.stack,
            "HeadNodeENI",
            description="AWS ParallelCluster head node interface",
            subnet_id=self.config.head_node.networking.subnet_id,
            source_dest_check=False,
            group_set=head_eni_group_set,
        )

        elastic_ip = self.config.head_node.networking.headnode_elastic_ip
        if elastic_ip:
            # Create and associate EIP to Head Node
            if elastic_ip is True:
                allocation_id = ec2.CfnEIP(self.stack, "HeadNodeEIP", domain="vpc").attr_allocation_id
            # Attach existing EIP
            else:
                allocation_id = AWSApi.instance().ec2.get_eip_allocation_id(elastic_ip)
            ec2.CfnEIPAssociation(
                self.stack, "AssociateEIP", allocation_id=allocation_id, network_interface_id=head_eni.ref
            )

        return head_eni

    def _add_security_groups(self):
        head_node_security_groups, managed_head_security_group = self._head_security_groups()
        (
            login_security_groups,
            managed_login_security_group,
            custom_login_security_groups,
        ) = self._login_security_groups()
        (
            compute_security_groups,
            managed_compute_security_group,
            custom_compute_security_groups,
        ) = self._compute_security_groups()

        self._add_inbounds_to_managed_security_groups(
            compute_security_groups,
            custom_compute_security_groups,
            head_node_security_groups,
            login_security_groups,
            custom_login_security_groups,
            managed_compute_security_group,
            managed_head_security_group,
            managed_login_security_group,
        )

        return managed_head_security_group, managed_compute_security_group, managed_login_security_group

    def _head_security_groups(self):
        managed_head_security_group = None
        custom_head_security_groups = self.config.head_node.networking.security_groups or []
        if not custom_head_security_groups:
            managed_head_security_group = self._add_head_security_group()
            head_node_security_groups = [managed_head_security_group.ref]
        else:
            head_node_security_groups = custom_head_security_groups
        return head_node_security_groups, managed_head_security_group

    def _login_security_groups(self):
        managed_login_security_group = None
        custom_login_security_groups = set()
        managed_login_security_group_required = False
        if self._condition_is_slurm() and self.config.login_nodes:
            for pool in self.config.login_nodes.pools:
                pool_security_groups = pool.networking.security_groups
                if pool_security_groups:
                    for security_group in pool_security_groups:
                        custom_login_security_groups.add(security_group)
                else:
                    managed_login_security_group_required = True
        login_security_groups = list(custom_login_security_groups)
        if managed_login_security_group_required:
            managed_login_security_group = self._add_login_nodes_security_group()
            login_security_groups.append(managed_login_security_group.ref)
        return login_security_groups, managed_login_security_group, custom_login_security_groups

    def _compute_security_groups(self):
        managed_compute_security_group = None
        custom_compute_security_groups = set()
        managed_compute_security_group_required = False
        for queue in self.config.scheduling.queues:
            queue_security_groups = queue.networking.security_groups
            if queue_security_groups:
                for security_group in queue_security_groups:
                    custom_compute_security_groups.add(security_group)
            else:
                managed_compute_security_group_required = True
        compute_security_groups = list(custom_compute_security_groups)
        if managed_compute_security_group_required:
            managed_compute_security_group = self._add_compute_security_group()
            compute_security_groups.append(managed_compute_security_group.ref)
        return compute_security_groups, managed_compute_security_group, custom_compute_security_groups

    def _add_inbounds_to_managed_security_groups(
        self,
        compute_security_groups,
        custom_compute_security_groups,
        head_node_security_groups,
        login_security_groups,
        custom_login_security_groups,
        managed_compute_security_group,
        managed_head_security_group,
        managed_login_security_group,
    ):
        self._add_inbounds_to_managed_head_security_group(
            compute_security_groups, login_security_groups, managed_head_security_group
        )

        self._add_inbounds_to_managed_login_security_group(
            head_node_security_groups,
            compute_security_groups,
            custom_login_security_groups,
            managed_login_security_group,
        )

        self._add_inbounds_to_managed_compute_security_group(
            head_node_security_groups,
            login_security_groups,
            custom_compute_security_groups,
            managed_compute_security_group,
        )

    def _add_inbounds_to_managed_head_security_group(
        self, compute_security_groups, login_security_groups, managed_head_security_group
    ):
        if managed_head_security_group:
            for index, security_group in enumerate(compute_security_groups):
                # Access to head node from compute nodes
                self._allow_all_ingress(
                    f"HeadNodeSecurityGroupComputeIngress{index}", security_group, managed_head_security_group.ref
                )
            for index, security_group in enumerate(login_security_groups):
                # Access to head node from login nodes
                self._allow_all_ingress(
                    f"HeadNodeSecurityGroupLoginSlurmIngress{index}",
                    security_group,
                    managed_head_security_group.ref,
                    ip_protocol="tcp",
                    port=SLURM_PORTS_RANGE,
                )
                self._allow_all_ingress(
                    f"HeadNodeSecurityGroupLoginNfsIngress{index}",
                    security_group,
                    managed_head_security_group.ref,
                    ip_protocol="tcp",
                    port=NFS_PORT,
                )

    def _add_inbounds_to_managed_login_security_group(
        self,
        head_node_security_groups,
        compute_security_groups,
        custom_login_security_groups,
        managed_login_security_group,
    ):
        if managed_login_security_group:
            # Access to login nodes from head node and compute nodes
            for index, security_group in enumerate(head_node_security_groups):
                self._allow_all_ingress(
                    f"LoginSecurityGroupHeadNodeIngress{index}", security_group, managed_login_security_group.ref
                )
            for index, security_group in enumerate(compute_security_groups):
                self._allow_all_ingress(
                    f"LoginSecurityGroupComputeIngress{index}", security_group, managed_login_security_group.ref
                )
            for index, security_group in enumerate(custom_login_security_groups):
                self._allow_all_ingress(
                    f"LoginSecurityGroupCustomLoginSecurityGroupIngress{index}",
                    security_group,
                    managed_login_security_group.ref,
                )

    def _add_inbounds_to_managed_compute_security_group(
        self,
        head_node_security_groups,
        login_security_groups,
        custom_compute_security_groups,
        managed_compute_security_group,
    ):
        if managed_compute_security_group:
            # Access to compute nodes from head node and login nodes
            for index, security_group in enumerate(head_node_security_groups):
                self._allow_all_ingress(
                    f"ComputeSecurityGroupHeadNodeIngress{index}",
                    security_group,
                    managed_compute_security_group.ref,
                )
            for index, security_group in enumerate(login_security_groups):
                self._allow_all_ingress(
                    f"ComputeSecurityGroupLoginIngress{index}",
                    security_group,
                    managed_compute_security_group.ref,
                )
            for index, security_group in enumerate(custom_compute_security_groups):
                self._allow_all_ingress(
                    f"ComputeSecurityGroupCustomComputeSecurityGroupIngress{index}",
                    security_group,
                    managed_compute_security_group.ref,
                )

    def _allow_all_ingress(self, description, source_security_group_id, group_id, ip_protocol="-1", port=(0, 65535)):
        return ec2.CfnSecurityGroupIngress(
            self.stack,
            description,
            ip_protocol=ip_protocol,
            from_port=port[0] if isinstance(port, collections.abc.Sequence) else port,
            to_port=port[1] if isinstance(port, collections.abc.Sequence) else port,
            source_security_group_id=source_security_group_id,
            group_id=group_id,
        )

    def _allow_all_egress(self, description, destination_security_group_id, group_id):
        return ec2.CfnSecurityGroupEgress(
            self.stack,
            description,
            ip_protocol="-1",
            from_port=0,
            to_port=65535,
            destination_security_group_id=destination_security_group_id,
            group_id=group_id,
        )

    def _add_storage_security_group(self, storage_cfn_id, storage):
        storage_type = storage.shared_storage_type
        storage_security_group = ec2.CfnSecurityGroup(
            self.stack,
            "{0}SecurityGroup".format(storage_cfn_id),
            group_description=f"Allow access to {storage_type} file system {storage_cfn_id}",
            vpc_id=self.config.vpc_id,
        )
        storage_deletion_policy = convert_deletion_policy(storage.deletion_policy)
        storage_security_group.cfn_options.deletion_policy = (
            storage_security_group.cfn_options.update_replace_policy
        ) = storage_deletion_policy

        target_security_groups = {
            "Head": self._get_head_node_security_groups(),
            "Compute": self._get_compute_security_groups(),
            "Login": self._get_login_security_groups(),
            "Storage": [storage_security_group.ref],
        }

        for sg_type, sg_refs in target_security_groups.items():
            for sg_ref_id, sg_ref in enumerate(sg_refs):
                # TODO Scope down ingress rules to allow only traffic on the strictly necessary ports.
                #      Currently scoped down only on Login nodes to limit blast radius.
                ingress_protocol = "-1"
                ingress_port = ALL_PORTS_RANGE
                if sg_type == "Login":
                    if storage_type == SharedStorageType.EFS:
                        ingress_protocol = "tcp"
                        ingress_port = EFS_PORT
                    elif storage_type == SharedStorageType.FSX:
                        ingress_protocol = "tcp"
                        ingress_port = FSX_PORTS[LUSTRE]["tcp"][0]
                ingress_rule = self._allow_all_ingress(
                    description=f"{storage_cfn_id}SecurityGroup{sg_type}Ingress{sg_ref_id}",
                    source_security_group_id=sg_ref,
                    group_id=storage_security_group.ref,
                    ip_protocol=ingress_protocol,
                    port=ingress_port,
                )

                egress_rule = self._allow_all_egress(
                    description=f"{storage_cfn_id}SecurityGroup{sg_type}Egress{sg_ref_id}",
                    destination_security_group_id=sg_ref,
                    group_id=storage_security_group.ref,
                )

                if sg_type == "Storage":
                    ingress_rule.cfn_options.deletion_policy = (
                        ingress_rule.cfn_options.update_replace_policy
                    ) = storage_deletion_policy
                    egress_rule.cfn_options.deletion_policy = (
                        egress_rule.cfn_options.update_replace_policy
                    ) = storage_deletion_policy

        return storage_security_group

    def _add_compute_security_group(self):
        compute_security_group = ec2.CfnSecurityGroup(
            self.stack,
            "ComputeSecurityGroup",
            group_description="Allow access to compute nodes",
            vpc_id=self.config.vpc_id,
        )

        # ComputeSecurityGroupEgress
        # Access to other compute nodes from compute nodes
        compute_security_group_egress = ec2.CfnSecurityGroupEgress(
            self.stack,
            "ComputeSecurityGroupEgress",
            ip_protocol="-1",
            from_port=0,
            to_port=65535,
            destination_security_group_id=compute_security_group.ref,
            group_id=compute_security_group.ref,
        )

        # ComputeSecurityGroupNormalEgress
        # Internet access from compute nodes
        ec2.CfnSecurityGroupEgress(
            self.stack,
            "ComputeSecurityGroupNormalEgress",
            ip_protocol="-1",
            from_port=0,
            to_port=65535,
            cidr_ip="0.0.0.0/0",
            group_id=compute_security_group.ref,
        ).add_depends_on(compute_security_group_egress)

        # ComputeSecurityGroupIngress
        # Access to compute nodes from other compute nodes
        ec2.CfnSecurityGroupIngress(
            self.stack,
            "ComputeSecurityGroupIngress",
            ip_protocol="-1",
            from_port=0,
            to_port=65535,
            source_security_group_id=compute_security_group.ref,
            group_id=compute_security_group.ref,
        )

        return compute_security_group

    def _add_login_nodes_security_group(self):
        login_nodes_security_group_ingress = [
            # SSH access
            ec2.CfnSecurityGroup.IngressProperty(
                ip_protocol="tcp",
                from_port=22,
                to_port=22,
                cidr_ip="0.0.0.0/0",
            )
        ]
        return ec2.CfnSecurityGroup(
            self.stack,
            "LoginNodesSecurityGroup",
            group_description="Enable access to the login nodes",
            vpc_id=self.config.vpc_id,
            security_group_ingress=login_nodes_security_group_ingress,
        )

    def _add_head_security_group(self):
        head_security_group_ingress = [
            # SSH access
            ec2.CfnSecurityGroup.IngressProperty(
                ip_protocol="tcp", from_port=22, to_port=22, cidr_ip=self.config.head_node.ssh.allowed_ips
            )
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
            self.stack,
            "HeadNodeSecurityGroup",
            group_description="Enable access to the head node",
            vpc_id=self.config.vpc_id,
            security_group_ingress=head_security_group_ingress,
        )

    def _add_shared_storage(self, storage):
        """Add specific Cfn Resources to map the shared storage and store the output filesystem id."""
        storage_list = self.shared_storage_infos[storage.shared_storage_type]
        cfn_resource_id = "{0}{1}".format(storage.shared_storage_type.name, create_hash_suffix(storage.name))
        if storage.shared_storage_type == SharedStorageType.FSX:
            storage_list.append(StorageInfo(self._add_fsx_storage(cfn_resource_id, storage), storage))
        elif storage.shared_storage_type == SharedStorageType.EBS:
            storage_list.append(StorageInfo(self._add_ebs_volume(cfn_resource_id, storage), storage))
        elif storage.shared_storage_type == SharedStorageType.EFS:
            storage_list.append(StorageInfo(self._add_efs_storage(cfn_resource_id, storage), storage))
        elif storage.shared_storage_type == SharedStorageType.RAID:
            storage_list.extend(self._add_raid_volume(cfn_resource_id, storage))
        self.shared_storage_mount_dirs[storage.shared_storage_type].append(storage.mount_dir)

    def _add_fsx_storage(self, id: str, shared_fsx: BaseSharedFsx):
        """Add specific Cfn Resources to map the FSX storage."""
        if isinstance(shared_fsx, SharedFsxLustre):
            fsx_id = shared_fsx.file_system_id
        elif isinstance(shared_fsx, ExistingFsxFileCache):
            fsx_id = shared_fsx.file_cache_id
        else:
            fsx_id = shared_fsx.volume_id
        mount_name = ""
        dns_name = ""
        volume_junction_path = ""
        if fsx_id:
            dns_name = shared_fsx.existing_dns_name
            if isinstance(shared_fsx, ExistingFsxOntap):
                volume_junction_path = shared_fsx.junction_path
            if isinstance(shared_fsx, ExistingFsxOpenZfs):
                volume_junction_path = shared_fsx.volume_path
            if isinstance(shared_fsx, SharedFsxLustre):
                mount_name = shared_fsx.existing_mount_name
            if isinstance(shared_fsx, ExistingFsxFileCache):
                mount_name = shared_fsx.file_cache_mount_name
        else:
            # Drive cache type must be set for HDD (Either "NONE" or "READ"), and must not be set for SDD (None).
            drive_cache_type = None
            if shared_fsx.fsx_storage_type == "HDD":
                if shared_fsx.drive_cache_type:
                    drive_cache_type = shared_fsx.drive_cache_type
                else:
                    drive_cache_type = "NONE"
            file_system_security_groups = [self._add_storage_security_group(id, shared_fsx)]
            fsx_resource = fsx.CfnFileSystem(
                self.stack,
                id,
                storage_capacity=shared_fsx.storage_capacity,
                lustre_configuration=fsx.CfnFileSystem.LustreConfigurationProperty(
                    deployment_type=shared_fsx.deployment_type,
                    data_compression_type=shared_fsx.data_compression_type,
                    imported_file_chunk_size=shared_fsx.imported_file_chunk_size,
                    export_path=shared_fsx.export_path,
                    import_path=shared_fsx.import_path,
                    weekly_maintenance_start_time=shared_fsx.weekly_maintenance_start_time,
                    automatic_backup_retention_days=shared_fsx.automatic_backup_retention_days,
                    copy_tags_to_backups=shared_fsx.copy_tags_to_backups,
                    daily_automatic_backup_start_time=shared_fsx.daily_automatic_backup_start_time,
                    per_unit_storage_throughput=shared_fsx.per_unit_storage_throughput,
                    auto_import_policy=shared_fsx.auto_import_policy,
                    drive_cache_type=drive_cache_type,
                ),
                backup_id=shared_fsx.backup_id,
                kms_key_id=shared_fsx.kms_key_id,
                file_system_type=LUSTRE,
                storage_type=shared_fsx.fsx_storage_type,
                subnet_ids=self.config.compute_subnet_ids[0:1],
                security_group_ids=[sg.ref for sg in file_system_security_groups],
                file_system_type_version=shared_fsx.file_system_type_version,
                tags=[CfnTag(key="Name", value=shared_fsx.name)],
            )
            fsx_resource.cfn_options.deletion_policy = (
                fsx_resource.cfn_options.update_replace_policy
            ) = convert_deletion_policy(shared_fsx.deletion_policy)

            fsx_id = fsx_resource.ref
            # Get MountName for new filesystem. DNSName cannot be retrieved from CFN and will be generated in cookbook
            mount_name = fsx_resource.attr_lustre_mount_name

        self.shared_storage_attributes[shared_fsx.shared_storage_type]["DNSNames"].append(dns_name)
        self.shared_storage_attributes[shared_fsx.shared_storage_type]["MountNames"].append(mount_name)
        self.shared_storage_attributes[shared_fsx.shared_storage_type]["VolumeJunctionPaths"].append(
            volume_junction_path
        )
        self.shared_storage_attributes[shared_fsx.shared_storage_type]["FileSystemTypes"].append(
            shared_fsx.file_system_type
        )

        return fsx_id

    def _add_efs_storage(self, id: str, shared_efs: SharedEfs):
        """Add specific Cfn Resources to map the EFS storage."""
        # EFS FileSystem
        efs_id = shared_efs.file_system_id
        deletion_policy = convert_deletion_policy(shared_efs.deletion_policy)
        if not efs_id and shared_efs.mount_dir:
            efs_resource = efs.CfnFileSystem(
                self.stack,
                id,
                encrypted=shared_efs.encrypted,
                kms_key_id=shared_efs.kms_key_id,
                performance_mode=shared_efs.performance_mode,
                provisioned_throughput_in_mibps=shared_efs.provisioned_throughput,
                throughput_mode=shared_efs.throughput_mode,
            )
            efs_resource.tags.set_tag(key="Name", value=shared_efs.name)
            efs_resource.cfn_options.deletion_policy = efs_resource.cfn_options.update_replace_policy = deletion_policy
            efs_id = efs_resource.ref

            # Create Mount Targets
            checked_availability_zones = []

            # Mount Targets for Compute Fleet
            compute_subnet_ids = self.config.compute_subnet_ids
            file_system_security_groups = [self._add_storage_security_group(id, shared_efs)]

            for subnet_id in compute_subnet_ids:
                self._add_efs_mount_target(
                    id,
                    efs_id,
                    file_system_security_groups,
                    subnet_id,
                    checked_availability_zones,
                    deletion_policy,
                )

            # Mount Target for Head Node
            self._add_efs_mount_target(
                id,
                efs_id,
                file_system_security_groups,
                self.config.head_node.networking.subnet_id,
                checked_availability_zones,
                deletion_policy,
            )

        self.shared_storage_attributes[SharedStorageType.EFS]["EncryptionInTransits"].append(
            shared_efs.encryption_in_transit
        )
        self.shared_storage_attributes[SharedStorageType.EFS]["IamAuthorizations"].append(shared_efs.iam_authorization)

        return efs_id

    def _add_efs_mount_target(
        self,
        efs_cfn_resource_id,
        file_system_id,
        security_groups,
        subnet_id,
        checked_availability_zones,
        deletion_policy,
    ):
        """Create a EFS Mount Point for the file system, if not already available on the same AZ."""
        availability_zone = AWSApi.instance().ec2.get_subnet_avail_zone(subnet_id)
        if availability_zone not in checked_availability_zones:
            efs_resource = efs.CfnMountTarget(
                self.stack,
                "{0}MT{1}".format(efs_cfn_resource_id, availability_zone),
                file_system_id=file_system_id,
                security_groups=[sg.ref for sg in security_groups],
                subnet_id=subnet_id,
            )
            efs_resource.cfn_options.deletion_policy = efs_resource.cfn_options.update_replace_policy = deletion_policy
            checked_availability_zones.append(availability_zone)

    def _add_raid_volume(self, id_prefix: str, shared_ebs: SharedEbs):
        """Add specific Cfn Resources to map the RAID EBS storage."""
        ebs_ids = []
        for index in range(shared_ebs.raid.number_of_volumes):
            ebs_ids.append(StorageInfo(self._add_cfn_volume(f"{id_prefix}Volume{index}", shared_ebs), shared_ebs))

        self.shared_storage_attributes[shared_ebs.shared_storage_type]["Type"] = str(shared_ebs.raid.raid_type)

        return ebs_ids

    def _add_ebs_volume(self, id: str, shared_ebs: SharedEbs):
        """Add specific Cfn Resources to map the EBS storage."""
        ebs_id = shared_ebs.volume_id
        if not ebs_id and shared_ebs.mount_dir:
            ebs_id = self._add_cfn_volume(id, shared_ebs)
        return ebs_id

    def _add_cfn_volume(self, id: str, shared_ebs: SharedEbs):
        volume = ec2.CfnVolume(
            self.stack,
            id,
            availability_zone=self.config.head_node.networking.availability_zone,
            encrypted=shared_ebs.encrypted,
            iops=shared_ebs.iops,
            throughput=shared_ebs.throughput,
            kms_key_id=shared_ebs.kms_key_id,
            size=shared_ebs.size,
            snapshot_id=shared_ebs.snapshot_id,
            volume_type=shared_ebs.volume_type,
            tags=[CfnTag(key="Name", value=shared_ebs.name)],
        )
        volume.cfn_options.deletion_policy = volume.cfn_options.update_replace_policy = convert_deletion_policy(
            shared_ebs.deletion_policy
        )
        return volume.ref

    def _add_wait_condition(self):
        wait_condition_handle = cfn.CfnWaitConditionHandle(
            self.stack, id="HeadNodeWaitConditionHandle" + self.timestamp
        )
        wait_condition = cfn.CfnWaitCondition(
            self.stack,
            id="HeadNodeWaitCondition" + self.timestamp,
            count=1,
            handle=wait_condition_handle.ref,
            timeout=str(
                get_attr(self.config, "dev_settings.timeouts.head_node_bootstrap_timeout", NODE_BOOTSTRAP_TIMEOUT)
            ),
        )
        return wait_condition, wait_condition_handle

    def _add_head_node(self):
        head_node = self.config.head_node
        head_lt_security_groups = self._get_head_node_security_groups_full()

        # LT network interfaces
        head_lt_nw_interfaces = [
            ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                device_index=0,
                network_interface_id=self._head_eni.ref,
            )
        ]
        for network_interface_index in range(1, head_node.max_network_interface_count):
            head_lt_nw_interfaces.append(
                ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                    device_index=1,
                    network_card_index=network_interface_index,
                    groups=head_lt_security_groups,
                    subnet_id=head_node.networking.subnet_id,
                )
            )

        cloudformation_url = get_service_endpoint("cloudformation", self.config.region)

        # Head node Launch Template
        head_node_launch_template = ec2.CfnLaunchTemplate(
            self.stack,
            "HeadNodeLaunchTemplate",
            launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
                instance_type=head_node.instance_type,
                block_device_mappings=self._launch_template_builder.get_block_device_mappings(
                    head_node.local_storage.root_volume,
                    AWSApi.instance().ec2.describe_image(self.config.head_node_ami).device_name,
                ),
                key_name=head_node.ssh.key_name,
                network_interfaces=head_lt_nw_interfaces,
                image_id=self.config.head_node_ami,
                ebs_optimized=head_node.is_ebs_optimized,
                iam_instance_profile=ec2.CfnLaunchTemplate.IamInstanceProfileProperty(
                    name=self._head_node_instance_profile
                ),
                metadata_options=ec2.CfnLaunchTemplate.MetadataOptionsProperty(
                    http_tokens=get_http_tokens_setting(self.config.imds.imds_support)
                ),
                user_data=Fn.base64(
                    Fn.sub(
                        get_user_data_content("../resources/head_node/user_data.sh"),
                        {
                            **{
                                "DisableMultiThreadingManually": "true"
                                if head_node.disable_simultaneous_multithreading_manually
                                else "false",
                                "CloudFormationUrl": cloudformation_url,
                            },
                            **get_common_user_data_env(head_node, self.config),
                        },
                    )
                ),
                tag_specifications=[
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="volume",
                        tags=get_default_volume_tags(self._stack_name, "HeadNode") + get_custom_tags(self.config),
                    ),
                ],
            ),
        )

        # Metadata
        head_node_launch_template.add_metadata("Comment", "AWS ParallelCluster Head Node")
        # CloudFormation::Init metadata

        dna_json = json.dumps(
            {
                "cluster": {
                    "stack_name": self._stack_name,
                    "stack_arn": self.stack.stack_id,
                    "raid_vol_ids": get_shared_storage_ids_by_type(self.shared_storage_infos, SharedStorageType.RAID),
                    "raid_shared_dir": to_comma_separated_string(
                        self.shared_storage_mount_dirs[SharedStorageType.RAID]
                    ),
                    "raid_type": to_comma_separated_string(
                        self.shared_storage_attributes[SharedStorageType.RAID]["Type"]
                    ),
                    "base_os": self.config.image.os,
                    "region": self.stack.region,
                    "efs_fs_ids": get_shared_storage_ids_by_type(self.shared_storage_infos, SharedStorageType.EFS),
                    "efs_shared_dirs": to_comma_separated_string(self.shared_storage_mount_dirs[SharedStorageType.EFS]),
                    "efs_encryption_in_transits": to_comma_separated_string(
                        self.shared_storage_attributes[SharedStorageType.EFS]["EncryptionInTransits"],
                        use_lower_case=True,
                    ),
                    "efs_iam_authorizations": to_comma_separated_string(
                        self.shared_storage_attributes[SharedStorageType.EFS]["IamAuthorizations"], use_lower_case=True
                    ),
                    "fsx_fs_ids": get_shared_storage_ids_by_type(self.shared_storage_infos, SharedStorageType.FSX),
                    "fsx_mount_names": to_comma_separated_string(
                        self.shared_storage_attributes[SharedStorageType.FSX]["MountNames"]
                    ),
                    "fsx_dns_names": to_comma_separated_string(
                        self.shared_storage_attributes[SharedStorageType.FSX]["DNSNames"]
                    ),
                    "fsx_volume_junction_paths": to_comma_separated_string(
                        self.shared_storage_attributes[SharedStorageType.FSX]["VolumeJunctionPaths"]
                    ),
                    "fsx_fs_types": to_comma_separated_string(
                        self.shared_storage_attributes[SharedStorageType.FSX]["FileSystemTypes"]
                    ),
                    "fsx_shared_dirs": to_comma_separated_string(self.shared_storage_mount_dirs[SharedStorageType.FSX]),
                    "volume": get_shared_storage_ids_by_type(self.shared_storage_infos, SharedStorageType.EBS),
                    "scheduler": self.config.scheduling.scheduler,
                    "ephemeral_dir": head_node.local_storage.ephemeral_volume.mount_dir
                    if head_node.local_storage.ephemeral_volume
                    else DEFAULT_EPHEMERAL_DIR,
                    "ebs_shared_dirs": to_comma_separated_string(self.shared_storage_mount_dirs[SharedStorageType.EBS]),
                    "proxy": head_node.networking.proxy.http_proxy_address if head_node.networking.proxy else "NONE",
                    "node_type": "HeadNode",
                    "cluster_user": OS_MAPPING[self.config.image.os]["user"],
                    "ddb_table": self.dynamodb_table_status.ref if not self._condition_is_batch() else "NONE",
                    "log_group_name": self.log_group.log_group_name
                    if self.config.monitoring.logs.cloud_watch.enabled
                    else "NONE",
                    "dcv_enabled": "head_node" if self.config.is_dcv_enabled else "false",
                    "dcv_port": head_node.dcv.port if head_node.dcv else "NONE",
                    "enable_intel_hpc_platform": "true" if self.config.is_intel_hpc_platform_enabled else "false",
                    "cw_logging_enabled": "true" if self.config.is_cw_logging_enabled else "false",
                    "log_rotation_enabled": "true" if self.config.is_log_rotation_enabled else "false",
                    "cluster_s3_bucket": self.bucket.name,
                    "cluster_config_s3_key": "{0}/configs/{1}".format(
                        self.bucket.artifact_directory, PCLUSTER_S3_ARTIFACTS_DICT.get("config_name")
                    ),
                    "cluster_config_version": self.config.config_version,
                    "change_set_s3_key": f"{self.bucket.artifact_directory}/configs/"
                    f"{PCLUSTER_S3_ARTIFACTS_DICT.get('change_set_name')}",
                    "instance_types_data_s3_key": f"{self.bucket.artifact_directory}/configs/"
                    f"{PCLUSTER_S3_ARTIFACTS_DICT.get('instance_types_data_name')}",
                    "custom_node_package": self.config.custom_node_package or "",
                    "custom_awsbatchcli_package": self.config.custom_aws_batch_cli_package or "",
                    "head_node_imds_secured": str(self.config.head_node.imds.secured).lower(),
                    "compute_node_bootstrap_timeout": get_attr(
                        self.config, "dev_settings.timeouts.compute_node_bootstrap_timeout", NODE_BOOTSTRAP_TIMEOUT
                    ),
                    **(
                        get_slurm_specific_dna_json_for_head_node(self.config, self.scheduler_resources)
                        if self._condition_is_slurm()
                        else {}
                    ),
                    **get_directory_service_dna_json_for_head_node(self.config),
                },
            },
            indent=4,
        )

        cfn_init = {
            "configSets": {
                "deployFiles": ["deployConfigFiles"],
                "default": [
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
                    "/etc/chef/client.rb": {
                        "mode": "000644",
                        "owner": "root",
                        "group": "root",
                        "content": "cookbook_path ['/etc/chef/cookbooks']",
                    },
                    # A nosec comment is appended to the following line in order to disable the B108 check.
                    # The file is needed by the product
                    # [B108:hardcoded_tmp_directory] Probable insecure usage of temp file/directory.
                    "/tmp/extra.json": {  # nosec B108
                        "mode": "000644",
                        "owner": "root",
                        "group": "root",
                        "content": self.config.extra_chef_attributes,
                    },
                    # A nosec comment is appended to the following line in order to disable the B108 check.
                    # The file is needed by the product
                    # [B108:hardcoded_tmp_directory] Probable insecure usage of temp file/directory.
                    "/tmp/wait_condition_handle.txt": {  # nosec B108
                        "mode": "000644",
                        "owner": "root",
                        "group": "root",
                        "content": self.wait_condition_handle.ref,
                    },
                },
                "commands": {
                    "mkdir": {"command": "mkdir -p /etc/chef/ohai/hints"},
                    "touch": {"command": "touch /etc/chef/ohai/hints/ec2.json"},
                    "jq": {
                        "command": (
                            "jq --argfile f1 /tmp/dna.json --argfile f2 /tmp/extra.json -n '$f1 * $f2' "
                            "> /etc/chef/dna.json "
                            '|| ( echo "jq not installed"; cp /tmp/dna.json /etc/chef/dna.json )'
                        )
                    },
                },
            },
            "cfnHupConfig": {
                "files": {
                    "/etc/cfn/hooks.d/parallelcluster-update.conf": {
                        "content": Fn.sub(
                            (
                                "[parallelcluster-update]\n"
                                "triggers=post.update\n"
                                "path=Resources.HeadNodeLaunchTemplate.Metadata.AWS::CloudFormation::Init\n"
                                "action=PATH=/usr/local/bin:/bin:/usr/bin:/opt/aws/bin; "
                                ". /etc/profile.d/pcluster.sh; "
                                "cfn-init -v --stack ${StackName} "
                                "--resource HeadNodeLaunchTemplate --configsets update "
                                "--region ${Region} "
                                "--url ${CloudFormationUrl}\n"
                                "runas=root\n"
                            ),
                            {
                                "StackName": self._stack_name,
                                "Region": self.stack.region,
                                "CloudFormationUrl": cloudformation_url,
                            },
                        ),
                        "mode": "000400",
                        "owner": "root",
                        "group": "root",
                    },
                    "/etc/cfn/cfn-hup.conf": {
                        "content": Fn.sub(
                            "[main]\n"
                            "stack=${StackId}\n"
                            "region=${Region}\n"
                            "url=${CloudFormationUrl}\n"
                            "interval=2\n",
                            {
                                "StackId": self.stack.stack_id,
                                "Region": self.stack.region,
                                "CloudFormationUrl": cloudformation_url,
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
                            "cinc-client --local-mode --config /etc/chef/client.rb --log_level info "
                            "--logfile /var/log/chef-client.log --force-formatter --no-color "
                            "--chef-zero-port 8889 --json-attributes /etc/chef/dna.json "
                            "--override-runlist aws-parallelcluster-entrypoints::init"
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
                            "cinc-client --local-mode --config /etc/chef/client.rb --log_level info "
                            "--logfile /var/log/chef-client.log --force-formatter --no-color "
                            "--chef-zero-port 8889 --json-attributes /etc/chef/dna.json "
                            "--override-runlist aws-parallelcluster-entrypoints::config"
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
                            "cinc-client --local-mode --config /etc/chef/client.rb --log_level info "
                            "--logfile /var/log/chef-client.log --force-formatter --no-color "
                            "--chef-zero-port 8889 --json-attributes /etc/chef/dna.json "
                            "--override-runlist aws-parallelcluster-entrypoints::finalize"
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
                            ". /etc/profile.d/pcluster.sh; "
                            "cinc-client --local-mode --config /etc/chef/client.rb --log_level info"
                            " --logfile /var/log/chef-client.log --force-formatter --no-color"
                            " --chef-zero-port 8889 --json-attributes /etc/chef/dna.json"
                            " --override-runlist aws-parallelcluster-entrypoints::update &&"
                            " /opt/parallelcluster/scripts/fetch_and_run -postupdate &&"
                            f" cfn-signal --exit-code=0 --reason='Update complete'"
                            f" --region {self.stack.region} --url {cloudformation_url}"
                            f" '{self.wait_condition_handle.ref}' ||"
                            f" cfn-signal --exit-code=1 --reason='Update failed'"
                            f" --region {self.stack.region} --url {cloudformation_url}"
                            f" '{self.wait_condition_handle.ref}'"
                        ),
                        "cwd": "/etc/chef",
                    }
                }
            },
        }

        if not self._condition_is_batch():
            cfn_init["deployConfigFiles"]["files"]["/opt/parallelcluster/shared/launch-templates-config.json"] = {
                "mode": "000644",
                "owner": "root",
                "group": "root",
                "content": self._get_launch_templates_config(),
            }

        head_node_launch_template.add_metadata("AWS::CloudFormation::Init", cfn_init)
        head_node_instance = ec2.CfnInstance(
            self.stack,
            "HeadNode",
            launch_template=ec2.CfnInstance.LaunchTemplateSpecificationProperty(
                launch_template_id=head_node_launch_template.ref,
                version=head_node_launch_template.attr_latest_version_number,
            ),
            tags=get_default_instance_tags(
                self._stack_name, self.config, head_node, "HeadNode", self.shared_storage_infos
            )
            + get_custom_tags(self.config),
        )
        if not self._condition_is_batch():
            head_node_instance.node.add_dependency(self.compute_fleet_resources)

        return head_node_instance

    def _get_launch_templates_config(self):
        if not self.compute_fleet_resources:
            return None

        lt_config = {"Queues": {}}
        for queue, compute_resources in self.compute_fleet_resources.launch_templates.items():
            lt_config["Queues"][queue] = {"ComputeResources": {}}
            for compute_resource, launch_template in compute_resources.items():
                lt_config["Queues"][queue]["ComputeResources"][compute_resource] = {
                    "LaunchTemplate": {"Id": launch_template.ref, "Version": launch_template.attr_latest_version_number}
                }

        return lt_config

    # -- Conditions -------------------------------------------------------------------------------------------------- #

    def _condition_create_lambda_iam_role(self):
        return (
            not self.config.iam
            or not self.config.iam.roles
            or not self.config.iam.roles.lambda_functions_role
            or self.config.iam.roles.get_param("lambda_functions_role").implied
        )

    def _condition_is_slurm(self):
        return self.config.scheduling.scheduler == "slurm"

    def _condition_is_batch(self):
        return self.config.scheduling.scheduler == "awsbatch"

    # -- Outputs ----------------------------------------------------------------------------------------------------- #

    def _add_outputs(self):
        # Storage filesystem Ids
        for storage_type, storage_list in self.shared_storage_infos.items():
            CfnOutput(
                self.stack,
                "{0}Ids".format(storage_type.name),
                description="{0} Filesystem IDs".format(storage_type.name),
                value=",".join(storage.id for storage in storage_list),
            )

        CfnOutput(
            self.stack,
            "HeadNodeInstanceID",
            description="ID of the head node instance",
            value=self.head_node_instance.ref,
        )

        CfnOutput(
            self.stack,
            "HeadNodePrivateIP",
            description="Private IP Address of the head node",
            value=self.head_node_instance.attr_private_ip,
        )

        CfnOutput(
            self.stack,
            "HeadNodePrivateDnsName",
            description="Private DNS name of the head node",
            value=self.head_node_instance.attr_private_dns_name,
        )
