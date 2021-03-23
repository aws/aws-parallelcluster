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
# This module contains all the classes representing the Resources objects.
# These objects are obtained from the configuration file through a conversion based on the Schema classes.
#
import json
import logging
import re
import time
from enum import Enum
from typing import List

import pkg_resources
import yaml
from marshmallow import ValidationError

from common.aws.aws_api import AWSApi
from common.aws.aws_resources import InstanceInfo, StackInfo
from common.boto3.common import AWSClientError
from pcluster.cli_commands.compute_fleet_status_manager import ComputeFleetStatus, ComputeFleetStatusManager
from pcluster.config.config_patch import ConfigPatch
from pcluster.constants import OS_MAPPING, PCLUSTER_NAME_MAX_LENGTH, PCLUSTER_NAME_REGEX, PCLUSTER_STACK_PREFIX
from pcluster.models.cluster_config import BaseClusterConfig, ClusterBucket, SlurmScheduling, Tag
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import (
    check_s3_bucket_exists,
    create_s3_bucket,
    generate_random_name_with_prefix,
    get_installed_version,
    get_stack_name,
    grouper,
    upload_resources_artifacts,
)
from pcluster.validators.common import FailureLevel, ValidationResult

LOGGER = logging.getLogger(__name__)


class NodeType(Enum):
    """Enum that identifies the cluster node type."""

    HEAD_NODE = "Master"  # FIXME HeadNode
    COMPUTE = "Compute"

    def __str__(self):
        return str(self.value)


class ClusterActionError(Exception):
    """Represent an error during the execution of an action on the cluster."""

    def __init__(self, message: str, validation_failures: list = None, update_changes: list = None):
        super().__init__(message)
        self.validation_failures = validation_failures or []
        self.update_changes = update_changes or []


class ClusterStack(StackInfo):
    """Class representing a running stack associated to a Cluster."""

    def __init__(self, stack_data: dict):
        """Init stack info."""
        super().__init__(stack_data)

    @property
    def cluster_name(self):
        """Return cluster name associated to this cluster."""
        return self.name[len(PCLUSTER_STACK_PREFIX) :]  # noqa: E203

    @property
    def template(self):
        """Return the template body of the stack."""
        try:
            return AWSApi.instance().cfn.get_stack_template(self.name)
        except AWSClientError as e:
            raise ClusterActionError(f"Unable to retrieve template for stack {self.name}. {e}")

    @property
    def version(self):
        """Return the version of ParallelCluster used to create the stack."""
        return self._get_tag("Version")

    @property
    def s3_bucket_name(self):
        """Return the name of the bucket used to store cluster information."""
        return self._get_output("ResourcesS3Bucket")

    @property
    def s3_artifact_directory(self):
        """Return the artifact directory of the bucket used to store cluster information."""
        return self._get_output("ArtifactS3RootDirectory")

    @property
    def head_node_user(self):
        """Return the output storing cluster user."""
        return self._get_output("ClusterUser")

    @property
    def head_node_ip(self):
        """Return the IP to be used to connect to the head node, public or private."""
        return self._get_output("MasterPublicIP") or self._get_output("MasterPrivateIP")

    @property
    def scheduler(self):
        """Return the scheduler used in the cluster."""
        return self._get_output("Scheduler")

    def get_cluster_config_dict(self):
        """Retrieve cluster config content."""
        if not self.s3_bucket_name:
            raise ClusterActionError("Unable to retrieve S3 Bucket name")
        if not self.s3_artifact_directory:
            raise ClusterActionError("Unable to retrieve Artifact S3 Root Directory")

        table_name = self.name
        config_version = None
        try:
            config_version_item = AWSApi.instance().dynamodb.get_item(table_name=table_name, key="CLUSTER_CONFIG")
            if config_version_item or "Item" in config_version_item:
                config_version = config_version_item["Item"].get("Version")
        except Exception:
            # Use latest if not found
            pass

        try:
            s3_object = AWSApi.instance().s3.get_object(
                bucket_name=self.s3_bucket_name,
                key=f"{self.s3_artifact_directory}/configs/cluster-config.yaml",
                version_id=config_version,
            )
            config_content = s3_object["Body"].read().decode("utf-8")
            return yaml.safe_load(config_content)
        except Exception as e:
            raise ClusterActionError(
                f"Unable to load configuration from bucket '{self.s3_bucket_name}/{self.s3_artifact_directory}'.\n{e}"
            )

    def updated_status(self):
        """Return updated status."""
        try:
            return AWSApi.instance().cfn.describe_stack(self.name).get("StackStatus")
        except AWSClientError as e:
            raise ClusterActionError(f"Unable to retrieve status of stack {self.name}. {e}")

    def delete(self, keep_logs: bool = True):
        """Delete stack by preserving logs."""
        if keep_logs:
            self._persist_cloudwatch_log_groups()
        AWSApi.instance().cfn.delete_stack(self.name)

    def _persist_cloudwatch_log_groups(self):
        """Enable cluster's CloudWatch log groups to persist past cluster deletion."""
        LOGGER.info("Configuring %s's CloudWatch log groups to persist past cluster deletion.", self.name)
        log_group_keys = self._get_unretained_cw_log_group_resource_keys()
        if log_group_keys:  # Only persist the CloudWatch group
            self._persist_stack_resources(log_group_keys)

    def _get_unretained_cw_log_group_resource_keys(self):
        """Return the keys to all CloudWatch log group resources in template if the resource is not to be retained."""
        unretained_cw_log_group_keys = []
        for key, resource in self.template.get("Resources", {}).items():
            if resource.get("Type") == "AWS::Logs::LogGroup" and resource.get("DeletionPolicy") != "Retain":
                unretained_cw_log_group_keys.append(key)
        return unretained_cw_log_group_keys

    def _persist_stack_resources(self, keys):
        """Set the resources in template identified by keys to have a DeletionPolicy of 'Retain'."""
        for key in keys:
            self.template["Resources"][key]["DeletionPolicy"] = "Retain"
        try:
            self._update_template()
        except AWSClientError as e:
            raise ClusterActionError(f"Unable to persist logs on cluster deletion, failed with error: {e}.")

    def _update_template(self):
        """Update template of the running stack according to self.template."""
        try:
            AWSApi.instance().cfn.update_stack(self.name, self.template, self._params)
            self._wait_for_update()
        except AWSClientError as e:
            if "no updates are to be performed" in str(e).lower():
                return  # If updated_template was the same as the stack's current one, consider the update a success
            raise e

    def _wait_for_update(self):
        """Wait for the given stack to be finished updating."""
        while self.updated_status() == "UPDATE_IN_PROGRESS":
            time.sleep(5)

    def get_default_user(self, os: str):
        """Get the default user for the given os."""
        return OS_MAPPING.get(os, []).get("user", None)

    @property
    def batch_compute_environment(self):
        """Return Batch compute environment."""
        return self._get_output("BatchComputeEnvironmentArn")


class Cluster:
    """Represent a running cluster, composed by a ClusterConfig and a ClusterStack."""

    def __init__(self, name: str, config: dict = None, stack: ClusterStack = None):
        self.name = name
        self.__source_config = config
        self.__stack = stack
        self.bucket = None
        self.template_body = None
        self.__config = None

        self.__has_running_capacity = None
        self.__running_capacity = None

    @property
    def stack(self):
        """Return the ClusterStack object."""
        if not self.__stack:
            try:
                self.__stack = ClusterStack(AWSApi.instance().cfn.describe_stack(self.stack_name))
            except AWSClientError as e:
                if f"Stack with id {self.stack_name} does not exist" in str(e):
                    raise ClusterActionError(f"Cluster {self.name} doesn't exist.")
                raise ClusterActionError(f"Unable to find cluster {self.name}. {e}")
        return self.__stack

    @property
    def source_config(self):
        """Return original config used to create the cluster."""
        if not self.__source_config:
            self.__source_config = self.stack.get_cluster_config_dict()
        return self.__source_config

    @property
    def config(self) -> BaseClusterConfig:
        """Return ClusterConfig object."""
        if not self.__config:
            try:
                self.__config = ClusterSchema().load(self.source_config)
            except ValidationError as e:
                raise ClusterActionError(f"Unable to parse configuration file. {e}")
        return self.__config

    @config.setter
    def config(self, value):
        self.__config = value

    @property
    def stack_name(self):
        """Return stack name."""
        return get_stack_name(self.name)

    @property
    def status(self):
        """Return the cluster status."""
        return self.stack.status

    def create(
        self,
        disable_rollback: bool = False,
        suppress_validators: bool = False,
        validation_failure_level: FailureLevel = FailureLevel.ERROR,
    ):
        """Create cluster."""
        creation_result = None
        try:
            # check cluster existence
            if AWSApi.instance().cfn.stack_exists(self.stack_name):
                raise ClusterActionError(f"Cluster {self.name} already exists")

            try:
                # syntactic validation
                self.config = ClusterSchema().load(self.source_config)

                # semantic validation
                if not suppress_validators:
                    validation_failures = self._validate_cluster_name()

                    LOGGER.info("Validating cluster configuration...")
                    validation_failures += self.config.validate()
                    for failure in validation_failures:
                        if failure.level.value >= FailureLevel(validation_failure_level).value:
                            # Raise the exception if there is a failure with a level greater than the specified one
                            raise ClusterActionError(
                                "Configuration is invalid", validation_failures=validation_failures
                            )

            except ValidationError as e:
                # syntactic failure
                validation_failures = [ValidationResult(str(e), FailureLevel.ERROR)]
                raise ClusterActionError("Configuration is invalid", validation_failures=validation_failures)

            # Create bucket if needed
            self.bucket = self._setup_cluster_bucket()

            self._add_version_tag()
            self._upload_config()

            # Create template if not provided by the user
            if not (self.config.dev_settings and self.config.dev_settings.cluster_template):
                self.template_body = CDKTemplateBuilder().build_cluster_template(
                    cluster_config=self.config, bucket=self.bucket, stack_name=self.stack_name
                )

            # upload cluster artifacts and generated template
            self._upload_artifacts()

            LOGGER.info("Creating stack named: %s", self.stack_name)
            creation_result = AWSApi.instance().cfn.create_stack_from_url(
                stack_name=self.stack_name,
                template_url=self.template_url,
                disable_rollback=disable_rollback,
                tags=self._get_cfn_tags(),
            )

            self.__stack = ClusterStack(AWSApi.instance().cfn.describe_stack(self.stack_name))
            LOGGER.debug("StackId: %s", self.stack.id)
            LOGGER.info("Status: %s", self.stack.status)

        except ClusterActionError as e:
            raise e
        except Exception as e:
            LOGGER.critical(e)
            if not creation_result and self.bucket:
                # Cleanup S3 artifacts if stack is not created yet
                self.bucket.delete()
            raise ClusterActionError(f"Cluster creation failed.\n{e}")

    def _validate_cluster_name(self):
        validation_failures = []
        if not re.match(PCLUSTER_NAME_REGEX % (PCLUSTER_NAME_MAX_LENGTH - 1), self.name):
            message = (
                "Error: The cluster name can contain only alphanumeric characters (case-sensitive) and hyphens. "
                "It must start with an alphabetic character and can't be longer "
                f"than {PCLUSTER_NAME_MAX_LENGTH} characters."
            )
            LOGGER.error(message)
            validation_failures.append(ValidationResult(str(message), FailureLevel.ERROR))
        return validation_failures

    def _setup_cluster_bucket(self) -> ClusterBucket:
        """
        Create pcluster bucket, if needed.

        If no bucket specified, create a bucket associated to the given stack.
        Created bucket needs to be removed on cluster deletion.
        """
        if self.config.cluster_s3_bucket:
            # Use user-provided bucket
            # Do not remove this bucket on deletion, but cleanup artifact directory
            name = self.config.cluster_s3_bucket
            remove_on_deletion = False
            try:
                check_s3_bucket_exists(name)
            except Exception as e:
                LOGGER.error("Unable to access config-specified S3 bucket %s: %s", name, e)
                raise e
        else:
            # Create 1 bucket per cluster named "parallelcluster-{random_string}" if bucket is not provided
            # This bucket needs to be removed on cluster deletion
            name = generate_random_name_with_prefix("parallelcluster")
            # self.cluster_s3_bucket = name
            remove_on_deletion = True
            LOGGER.debug("Creating S3 bucket for cluster resources, named %s", name)
            try:
                create_s3_bucket(name)
            except Exception as e:
                LOGGER.error("Unable to create S3 bucket %s.", name)
                raise e

        # Use "{stack_name}-{random_string}" as directory in bucket
        artifact_directory = generate_random_name_with_prefix(self.stack_name)
        return ClusterBucket(name, artifact_directory, remove_on_deletion)

    def _upload_config(self):
        """Upload source config and save config version."""
        if not self.bucket:
            ClusterActionError("S3 bucket must be created before uploading artifacts.")

        try:
            # Upload original config
            if self.config.source_config:
                result = AWSApi.instance().s3.put_object(
                    bucket_name=self.bucket.name,
                    body=yaml.dump(self.config.source_config),
                    key=self._get_config_key(),
                )
                # config version will be stored in DB by the cookbook at the first update
                self.config.config_version = result.get("VersionId")

        except Exception as e:
            raise ClusterActionError(
                f"Unable to upload cluster config to the S3 bucket {self.bucket.name} due to exception: {e}"
            )

    def _upload_artifacts(self):
        """
        Upload cluster specific resources and cluster template.

        Artifacts are uploaded to {bucket_name}/{artifact_directory}/.
        {artifact_directory}/ will be always be cleaned up on cluster deletion or in case of failure.
        """
        if not self.bucket:
            ClusterActionError("S3 bucket must be created before uploading artifacts.")

        try:
            resources = pkg_resources.resource_filename(__name__, "../resources/custom_resources")
            upload_resources_artifacts(self.bucket.name, self.bucket.artifact_directory, root=resources)
            if self.config.scheduler_resources:
                upload_resources_artifacts(
                    self.bucket.name, self.bucket.artifact_directory, root=self.config.scheduler_resources
                )

            # Upload template
            if self.template_body:
                AWSApi.instance().s3.put_object(
                    bucket_name=self.bucket.name,
                    body=yaml.dump(self.template_body),
                    key=self._get_default_template_key(),
                )

            # Fixme: the code doesn't work for awsbatch
            if isinstance(self.config.scheduling, SlurmScheduling):
                AWSApi.instance().s3.put_object(
                    bucket_name=self.bucket.name,
                    body=json.dumps(self.config.get_instance_types_data()),
                    key=self._get_instance_types_data_key(),
                )
        except Exception as e:
            message = f"Unable to upload cluster resources to the S3 bucket {self.bucket.name} due to exception: {e}"
            LOGGER.error(message)
            raise ClusterActionError(message)

    @property
    def template_url(self):
        """Return template url."""
        if self.config.dev_settings and self.config.dev_settings.cluster_template:
            # template provided by the user
            template_url = self.config.dev_settings.cluster_template
        else:
            # default template
            template_url = "https://{bucket_name}.s3.{region}.amazonaws.com{partition_suffix}/{template_key}".format(
                bucket_name=self.bucket.name,
                region=self.config.region,
                partition_suffix=".cn" if self.config.region.startswith("cn") else "",
                template_key=self._get_default_template_key(),
            )
        return template_url

    def _get_default_template_key(self):
        return f"{self.bucket.artifact_directory}/templates/aws-parallelcluster.cfn.yaml"

    def _get_config_key(self):
        return f"{self.bucket.artifact_directory}/configs/cluster-config.yaml"

    def _get_instance_types_data_key(self):
        return f"{self.bucket.artifact_directory}/configs/instance-types-data.json"

    def delete(self, keep_logs: bool = True):
        """Delete cluster."""
        try:
            self.stack.delete(keep_logs)
            self._terminate_nodes()
        except Exception as e:
            self._terminate_nodes()
            raise ClusterActionError(f"Cluster {self.name} did not delete successfully. {e}")

    def _terminate_nodes(self):
        try:
            LOGGER.info("\nChecking if there are running compute nodes that require termination...")
            filters = self._get_instance_filters(node_type=NodeType.COMPUTE)
            instances = AWSApi.instance().ec2.list_instance_ids(filters)

            for instance_ids in grouper(instances, 100):
                LOGGER.info("Terminating following instances: %s", instance_ids)
                if instance_ids:
                    AWSApi.instance().ec2.terminate_instances(instance_ids)

            LOGGER.info("Compute fleet cleaned up.")
        except Exception as e:
            LOGGER.error("Failed when checking for running EC2 instances with error: %s", str(e))

    @property
    def compute_instances(self) -> List[InstanceInfo]:
        """Get compute instances."""
        return self._describe_instances(node_type=NodeType.COMPUTE)

    @property
    def head_node_instance(self) -> InstanceInfo:
        """Get head node instance."""
        try:
            return self._describe_instances(node_type=NodeType.HEAD_NODE)[0]
        except IndexError:
            raise ClusterActionError("Unable to retrieve head node information.")

    def _get_instance_filters(self, node_type: NodeType):
        return [
            {"Name": "tag:Application", "Values": [self.stack_name]},
            {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
            {"Name": "tag:aws-parallelcluster-node-type", "Values": [node_type.value]},
        ]

    def _describe_instances(self, node_type: NodeType):
        """Return the cluster instances filtered by node type."""
        try:
            filters = self._get_instance_filters(node_type)
            return AWSApi.instance().ec2.describe_instances(filters)
        except AWSClientError as e:
            raise ClusterActionError(f"Failed to retrieve cluster instances. {e}")

    @property
    def head_node_user(self):
        """Return the default user for the head node."""
        user = self.stack.get_default_user(self.config.image.os)
        if not user:
            raise ClusterActionError("Failed to get cluster {0} username.".format(self.name))
        return user

    @property
    def head_node_ip(self):
        """Get the IP Address of the head node."""
        stack_status = self.stack.updated_status()
        if stack_status in ["DELETE_COMPLETE", "DELETE_IN_PROGRESS"]:
            raise ClusterActionError(
                "Unable to retrieve head node ip for a stack in the status: {0}".format(stack_status)
            )

        head_node = self.head_node_instance
        if not head_node:
            raise ClusterActionError("Head node not running.")

        ip_address = head_node.public_ip
        if ip_address is None:
            ip_address = head_node.private_ip

        if head_node.state != "running" or ip_address is None:
            raise ClusterActionError("Head node: {0}\nCannot get ip address.".format(head_node.state.upper()))
        return ip_address

    def has_running_capacity(self, updated_value: bool = False):
        """Return True if the cluster has running capacity. Note: the value will be cached."""
        if self.__has_running_capacity is None or updated_value:
            if self.stack.scheduler == "slurm":
                self.__has_running_capacity = (
                    ComputeFleetStatusManager(self.name).get_status() != ComputeFleetStatus.STOPPED
                )
            elif self.stack.scheduler == "awsbatch":
                self.__has_running_capacity = self.get_running_capacity() > 0
        return self.__has_running_capacity

    def get_running_capacity(self, updated_value: bool = False):
        """Return the number of instances or desired capacity. Note: the value will be cached."""
        if self.__running_capacity is None or updated_value:
            if self.stack.scheduler == "slurm":
                self.__running_capacity = len(self.compute_instances)
            elif self.stack.scheduler == "awsbatch":
                self.__running_capacity = AWSApi.instance().batch.get_compute_environment_capacity(
                    ce_name=self.stack.batch_compute_environment,
                )
        return self.__running_capacity

    def start(self):
        """Start the cluster."""
        try:
            scheduler = self.config.scheduling.scheduler
            if scheduler == "awsbatch":
                LOGGER.info("Enabling AWS Batch compute environment : %s", self.name)
                try:
                    compute_resource = self.config.scheduling.queues[0].compute_resources[0]

                    AWSApi.instance().batch.enable_compute_environment(
                        ce_name=self.stack.batch_compute_environment,
                        min_vcpus=compute_resource.min_vcpus,
                        max_vcpus=compute_resource.max_vcpus,
                        desired_vcpus=compute_resource.desired_vcpus,
                    )
                except Exception as e:
                    raise ClusterActionError(f"Unable to enable Batch compute environment. {str(e)}")

            else:  # scheduler == "slurm"
                stack_status = self.stack.status
                if "IN_PROGRESS" in stack_status:
                    raise ClusterActionError(f"Cannot start compute fleet while stack is in {stack_status} status.")
                if "FAILED" in stack_status:
                    LOGGER.warning("Cluster stack is in %s status. This operation might fail.", stack_status)

                compute_fleet_status_manager = ComputeFleetStatusManager(self.name)
                compute_fleet_status_manager.update_status(
                    ComputeFleetStatus.START_REQUESTED, ComputeFleetStatus.STARTING, ComputeFleetStatus.RUNNING
                )
        except ComputeFleetStatusManager.ConditionalStatusUpdateFailed:
            raise ClusterActionError(
                "Failed when starting compute fleet due to a concurrent update of the status. "
                "Please retry the operation."
            )
        except ClusterActionError as e:
            raise e
        except Exception as e:
            raise ClusterActionError(f"Failed when starting compute fleet with error: {str(e)}")

    def stop(self):
        """Stop compute fleet of the cluster."""
        try:
            scheduler = self.config.scheduling.scheduler
            if scheduler == "awsbatch":
                LOGGER.info("Disabling AWS Batch compute environment : %s", self.name)
                try:
                    AWSApi.instance().batch.disable_compute_environment(ce_name=self.stack.batch_compute_environment)
                except Exception as e:
                    raise ClusterActionError(f"Unable to disable Batch compute environment. {str(e)}")

            else:  # scheduler == "slurm"
                stack_status = self.stack.status
                if "IN_PROGRESS" in stack_status:
                    raise ClusterActionError(f"Cannot stop compute fleet while stack is in {stack_status} status.")
                if "FAILED" in stack_status:
                    LOGGER.warning("Cluster stack is in %s status. This operation might fail.", stack_status)

                compute_fleet_status_manager = ComputeFleetStatusManager(self.name)
                compute_fleet_status_manager.update_status(
                    ComputeFleetStatus.STOP_REQUESTED, ComputeFleetStatus.STOPPING, ComputeFleetStatus.STOPPED
                )
        except ComputeFleetStatusManager.ConditionalStatusUpdateFailed:
            raise ClusterActionError(
                "Failed when stopping compute fleet due to a concurrent update of the status. "
                "Please retry the operation."
            )
        except ClusterActionError as e:
            raise e
        except Exception as e:
            raise ClusterActionError(f"Failed when stopping compute fleet with error: {str(e)}")

    def update(
        self,
        cluster_config: dict,
        suppress_validators: bool = False,
        validation_failure_level: FailureLevel = FailureLevel.ERROR,
        force: bool = False,
    ):
        """Update cluster."""
        try:
            # check cluster existence
            if not AWSApi.instance().cfn.stack_exists(self.stack_name):
                raise ClusterActionError(f"Cluster {self.name} does not exist")

            if "IN_PROGRESS" in self.stack.status:
                raise ClusterActionError(f"Cannot execute update while stack is in {self.stack.status} status.")

            if not suppress_validators:
                LOGGER.info("Validating cluster configuration...")
                try:
                    # syntactic validation
                    target_config = ClusterSchema().load(cluster_config)
                    # semantic validation
                    validation_failures = target_config.validate()
                except ValidationError as e:
                    validation_failures = [ValidationResult(str(e), FailureLevel.ERROR)]

                for failure in validation_failures:
                    if failure.level.value >= FailureLevel(validation_failure_level).value:
                        # Raise the exception if there is a failure with a level greater than the specified one
                        raise ClusterActionError("Configuration is invalid", validation_failures=validation_failures)
                LOGGER.info("Validation succeeded.")

            patch = ConfigPatch(cluster=self, base_config=self.source_config, target_config=cluster_config)
            patch_allowed, update_changes = patch.check()
            if not (patch_allowed or force):
                raise ClusterActionError("Update failure", update_changes=update_changes)

            # Retrieve bucket information
            self.bucket = ClusterBucket(
                name=self.stack.s3_bucket_name,
                artifact_directory=self.stack.s3_artifact_directory,
                remove_on_deletion=True,
            )
            self._add_version_tag()
            self._upload_config()

            # Create template if not provided by the user
            if not (self.config.dev_settings and self.config.dev_settings.cluster_template):
                self.template_body = CDKTemplateBuilder().build_cluster_template(
                    cluster_config=self.config, bucket=self.bucket, stack_name=self.stack_name
                )

            # upload cluster artifacts and generated template
            self._upload_artifacts()

            LOGGER.info("Updating stack named: %s", self.stack_name)
            AWSApi.instance().cfn.update_stack_from_url(
                stack_name=self.stack_name,
                template_url=self.template_url,
                tags=self._get_cfn_tags(),
            )

            self.__stack = ClusterStack(AWSApi.instance().cfn.describe_stack(self.stack_name))
            LOGGER.debug("StackId: %s", self.stack.id)
            LOGGER.info("Status: %s", self.stack.status)

        except ClusterActionError as e:
            raise e
        except Exception as e:
            LOGGER.critical(e)
            raise ClusterActionError(f"Cluster update failed.\n{e}")

    def _add_version_tag(self):
        """Add version tag to the stack."""
        if self.config.tags is None:
            self.config.tags = []
        self.config.tags.append(Tag(key="Version", value=get_installed_version()))

    def _get_cfn_tags(self):
        """Return tag list in the format expected by CFN."""
        return [{"Key": tag.key, "Value": tag.value} for tag in self.config.tags]
