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
from aws_cdk.core import CfnCustomResource, CfnResource, Construct, Stack

from pcluster.config.cluster_config import SlurmClusterConfig
from pcluster.constants import (
    MAX_COMPUTE_RESOURCES_PER_DEPLOYMENT_WAVE,
    MAX_COMPUTE_RESOURCES_PER_QUEUE,
    PCLUSTER_CLUSTER_NAME_TAG,
)
from pcluster.templates.queue_group_stack import QueueGroupStack
from pcluster.templates.slurm_builder import SlurmConstruct
from pcluster.utils import LOGGER, batch_by_property_callback


class QueueBatchConstruct(Construct):
    """
    CDK Construct for the batch of Groups of Queue Stacks.

    This prevents  exceeding the AWS API Request Limit.
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        queue_cohort,
        cluster_config: SlurmClusterConfig,
        log_group: logs.CfnLogGroup,
        shared_storage_infos: Dict,
        shared_storage_mount_dirs: Dict,
        shared_storage_attributes: Dict,
        cluster_hosted_zone,
        dynamodb_table,
        head_eni,
        slurm_construct: SlurmConstruct,
        compute_security_group,
    ):
        super().__init__(scope, id)
        self._config = cluster_config
        self._shared_storage_infos = shared_storage_infos
        self._shared_storage_mount_dirs = shared_storage_mount_dirs
        self._shared_storage_attributes = shared_storage_attributes
        self._log_group = log_group
        self._cluster_hosted_zone = cluster_hosted_zone
        self._dynamodb_table = dynamodb_table
        self._head_eni = head_eni
        self._slurm_construct = slurm_construct
        self._compute_security_group = compute_security_group

        self.compute_fleet_launch_templates = {}
        self.managed_compute_fleet_instance_roles = {}
        self.managed_compute_fleet_placement_groups = {}
        self.queue_cohort = queue_cohort
        self.queue_group_stacks = []
        self._add_resources()

    def _add_resources(self):
        queue_groups = batch_by_property_callback(
            self._config.scheduling.queues,
            lambda q: len(q.compute_resources),
            MAX_COMPUTE_RESOURCES_PER_QUEUE,
        )
        for group_index, queue_group in enumerate(queue_groups):
            LOGGER.info(f"QueueGroup{group_index}: {[queue.name for queue in queue_group]}")
            queue_group_stack = QueueGroupStack(
                scope=self,
                id=f"QueueGroup{group_index}",
                queues=queue_group,
                cluster_config=self._config,
                log_group=self._log_group,
                shared_storage_infos=self._shared_storage_infos,
                shared_storage_mount_dirs=self._shared_storage_mount_dirs,
                shared_storage_attributes=self._shared_storage_attributes,
                cluster_hosted_zone=self._cluster_hosted_zone,
                dynamodb_table=self._dynamodb_table,
                head_eni=self._head_eni,
                slurm_construct=self._slurm_construct,
                compute_security_group=self._compute_security_group,
            )
            self.managed_compute_fleet_instance_roles.update(queue_group_stack.managed_compute_instance_roles)
            self.compute_fleet_launch_templates.update(queue_group_stack.compute_launch_templates)
            self.managed_compute_fleet_placement_groups.update(queue_group_stack.managed_placement_groups)
            self.queue_group_stacks.append(queue_group_stack)


class ComputeFleetConstruct(Construct):
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
        self._slurm_construct = slurm_construct

        self.launch_templates = {}
        self.managed_compute_fleet_instance_roles = {}
        self.managed_compute_fleet_placement_groups = {}

        self._add_resources()

    # -- Utility methods --------------------------------------------------------------------------------------------- #

    @property
    def stack_name(self):
        """Name of the CFN stack."""
        return Stack.of(self).stack_name

    @property
    def managed_compute_instance_roles(self) -> Dict[str, iam.Role]:
        """Mapping of each queue and the IAM role associated with its compute resources."""
        return self.managed_compute_fleet_instance_roles

    def _add_resources(self):
        queue_batches = batch_by_property_callback(
            self._config.scheduling.queues,
            lambda q: len(q.compute_resources),
            MAX_COMPUTE_RESOURCES_PER_DEPLOYMENT_WAVE,
        )

        queue_deployment_groups = []
        for batch_index, queue_batch in enumerate(queue_batches):
            queue_deployment_groups.append(
                QueueBatchConstruct(
                    scope=self,
                    id=f"QueueBatch{batch_index}",
                    queue_cohort=queue_batch,
                    cluster_config=self._config,
                    log_group=self._log_group,
                    shared_storage_infos=self._shared_storage_infos,
                    shared_storage_mount_dirs=self._shared_storage_mount_dirs,
                    shared_storage_attributes=self._shared_storage_attributes,
                    cluster_hosted_zone=self._cluster_hosted_zone,
                    dynamodb_table=self._dynamodb_table,
                    head_eni=self._head_eni,
                    slurm_construct=self._slurm_construct,
                    compute_security_group=self._compute_security_group,
                )
            )

        for group_index, queue_deployment_group in enumerate(queue_deployment_groups):
            self.managed_compute_fleet_instance_roles.update(
                queue_deployment_group.managed_compute_fleet_instance_roles
            )
            self.launch_templates.update(queue_deployment_group.compute_fleet_launch_templates)
            self.managed_compute_fleet_placement_groups.update(
                queue_deployment_group.managed_compute_fleet_placement_groups
            )
            # Make each deployment group dependent on the previous deployment group, this way the stack creation
            # of all compute fleet resources will not happen concurrently (avoiding throttling)
            if group_index < len(queue_deployment_groups) - 1:
                queue_deployment_groups[group_index + 1].node.add_dependency(queue_deployment_groups[group_index])

        custom_resource_deps = list(self.managed_compute_fleet_placement_groups.values())
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
