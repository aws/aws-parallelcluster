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
import logging
import time
from copy import deepcopy
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
from pcluster.constants import OS_MAPPING, PCLUSTER_STACK_PREFIX
from pcluster.models.cluster_config import BaseClusterConfig, SlurmScheduling, Tag
from pcluster.models.common import S3Bucket, S3BucketFactory, S3FileFormat
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import generate_random_name_with_prefix, get_installed_version, get_region, grouper
from pcluster.validators.cluster_validators import ClusterNameValidator
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
            return yaml.safe_load(AWSApi.instance().cfn.get_stack_template(self.name))
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

    def updated_status(self):
        """Return updated status."""
        try:
            return AWSApi.instance().cfn.describe_stack(self.name).get("StackStatus")
        except AWSClientError as e:
            raise ClusterActionError(f"Unable to retrieve status of stack {self.name}. {e}")

    def delete(self):
        """Delete stack."""
        AWSApi.instance().cfn.delete_stack(self.name)

    def update_template(self, template_url):
        """Update template of the running stack according to updated template."""
        try:
            AWSApi.instance().cfn.update_stack_from_url(self.name, template_url)
            self._wait_for_update()
        except AWSClientError as e:
            if "no updates are to be performed" in str(e).lower():
                return  # If updated_template was the same as the stack's current one, consider the update a success
            raise e

    def _wait_for_update(self):
        """Wait for the given stack to be finished updating."""
        while self.updated_status() == "UPDATE_IN_PROGRESS":
            time.sleep(5)
        while self.updated_status() == "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS":
            time.sleep(2)

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
        self.__bucket = None
        self.template_body = None
        self.__config = None
        self._s3_artifacts_dict = {
            "root_directory": "parallelcluster",
            "root_cluster_directory": "clusters",
            "source_config_name": "cluster-config-original.yaml",
            "config_name": "cluster-config.yaml",
            "template_name": "aws-parallelcluster.cfn.yaml",
            "instance_types_data_name": "instance-types-data.json",
            "custom_artifacts_name": "artifacts.zip",
            "scheduler_resources_name": "scheduler_resources.zip",
        }
        self.__s3_artifact_dir = None

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
            self.__source_config = self._get_cluster_config_dict()
        return self.__source_config

    @property
    # pylint: disable=R0801
    def s3_artifacts_dir(self):
        """Get s3 artifacts dir."""
        if self.__s3_artifact_dir is None:
            self._get_artifact_dir()
        return self.__s3_artifact_dir

    def _get_artifact_dir(self):
        """Get artifact directory in S3 bucket by stack output."""
        try:
            self.__s3_artifact_dir = self.stack.s3_artifact_directory
            if self.__s3_artifact_dir is None:
                raise AWSClientError(
                    function_name="_get_artifact_dir", message="No artifact dir found in cluster stack output."
                )
        except AWSClientError as e:
            LOGGER.error("No artifact dir found in cluster stack output.")
            raise ClusterActionError(f"Unable to find artifact dir in cluster stack {self.stack_name} output. {e}")

    def _generate_artifact_dir(self):
        """
        Generate artifact directory in S3 bucket.

        cluster artifact dir is generated before cfn stack creation and only generate once.
        artifact_directory: e.g. parallelcluster/clusters/{cluster_name}-jfr4odbeonwb1w5k
        """
        service_directory = generate_random_name_with_prefix(self.name)
        self.__s3_artifact_dir = "/".join(
            [
                self._s3_artifacts_dict.get("root_directory"),
                self._s3_artifacts_dict.get("root_cluster_directory"),
                service_directory,
            ]
        )

    def _get_cluster_config_dict(self):
        """Retrieve cluster config content."""
        table_name = self.stack.name
        config_version = None
        try:
            config_version_item = AWSApi.instance().dynamodb.get_item(table_name=table_name, key="CLUSTER_CONFIG")
            if config_version_item or "Item" in config_version_item:
                config_version = config_version_item["Item"].get("Version")
        except Exception:  # nosec
            # Use latest if not found
            pass

        try:
            return self.bucket.get_config(
                version_id=config_version, config_name=self._s3_artifacts_dict.get("config_name")
            )
        except Exception as e:
            raise ClusterActionError(
                f"Unable to load configuration from bucket '{self.bucket.name}/{self.s3_artifacts_dir}'.\n{e}"
            )

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
        return PCLUSTER_STACK_PREFIX + self.name

    @property
    def status(self):
        """Return the cluster status."""
        return self.stack.status

    @property
    # pylint: disable=R0801
    def bucket(self):
        """Return a bucket configuration."""
        if self.__bucket:
            return self.__bucket

        if self.__source_config:
            # get custom_s3_bucket in create command
            custom_bucket_name = self.config.custom_s3_bucket
        else:
            # get custom_s3_bucket in delete, update commands
            custom_bucket_name = self.stack.s3_bucket_name
            if custom_bucket_name == S3Bucket.get_bucket_name(AWSApi.instance().sts.get_account_id(), get_region()):
                custom_bucket_name = None

        try:
            self.__bucket = S3BucketFactory.init_s3_bucket(
                service_name=self.name,
                stack_name=self.stack_name,
                custom_s3_bucket=custom_bucket_name,
                artifact_directory=self.s3_artifacts_dir,
            )
        except AWSClientError as e:
            raise ClusterActionError(f"Unable to initialize s3 bucket. {e}")

        return self.__bucket

    def create(
        self,
        disable_rollback: bool = False,
        suppress_validators: bool = False,
        validation_failure_level: FailureLevel = FailureLevel.ERROR,
    ):
        """Create cluster."""
        creation_result = None
        artifacts_uploaded = False
        try:
            # check cluster existence
            if AWSApi.instance().cfn.stack_exists(self.stack_name):
                raise ClusterActionError(f"Cluster {self.name} already exists")
            self.config = self._validate_and_parse_config(suppress_validators, validation_failure_level)

            self._generate_artifact_dir()
            self._add_version_tag()
            self._upload_config()

            # Create template if not provided by the user
            if not (self.config.dev_settings and self.config.dev_settings.cluster_template):
                self.template_body = CDKTemplateBuilder().build_cluster_template(
                    cluster_config=self.config, bucket=self.bucket, stack_name=self.stack_name
                )

            # upload cluster artifacts and generated template
            self._upload_artifacts()
            artifacts_uploaded = True

            LOGGER.info("Creating stack named: %s", self.stack_name)
            creation_result = AWSApi.instance().cfn.create_stack_from_url(
                stack_name=self.stack_name,
                template_url=self.bucket.get_cfn_template_url(
                    template_name=self._s3_artifacts_dict.get("template_name")
                ),
                disable_rollback=disable_rollback,
                tags=self._get_cfn_tags(),
            )

            self.__stack = ClusterStack(AWSApi.instance().cfn.describe_stack(self.stack_name))
            LOGGER.debug("StackId: %s", self.stack.id)
            LOGGER.info("Status: %s", self.stack.status)

        except Exception as e:
            if not creation_result and artifacts_uploaded:
                # Cleanup S3 artifacts if stack is not created yet
                self.bucket.delete_s3_artifacts()
            raise ClusterActionError(f"Cluster creation failed.\n{e}")

    def _validate_and_parse_config(self, suppress_validators, validation_failure_level, config_dict=None):
        """
        Perform semantic and syntactic validation and return parsed config.

        :param config_dict: config to parse, self.source_config will be used if not specified.
        """
        try:
            LOGGER.info("Validating cluster configuration...")
            # syntactic validation
            cluster_config_dict = config_dict or self.source_config
            config = ClusterSchema().load(cluster_config_dict)

            # semantic validation
            if not suppress_validators:
                validation_failures = ClusterNameValidator().execute(name=self.name)
                validation_failures += config.validate()
                for failure in validation_failures:
                    if failure.level.value >= FailureLevel(validation_failure_level).value:
                        # Raise the exception if there is a failure with a level greater than the specified one
                        raise ClusterActionError("Configuration is invalid", validation_failures=validation_failures)
            LOGGER.info("Validation succeeded.")

        except ValidationError as e:
            # syntactic failure
            validation_failures = [ValidationResult(str(e), FailureLevel.ERROR)]
            raise ClusterActionError("Configuration is invalid", validation_failures=validation_failures)

        return config

    def _upload_config(self):
        """Upload source config and save config version."""
        try:
            # Upload config with default values and sections
            if self.config:
                result = self.bucket.upload_config(
                    config=ClusterSchema().dump(deepcopy(self.config)),
                    config_name=self._s3_artifacts_dict.get("config_name"),
                )

                # config version will be stored in DB by the cookbook at the first update
                self.config.config_version = result.get("VersionId")

                # Upload original config
                self.bucket.upload_config(
                    config=self.config.source_config, config_name=self._s3_artifacts_dict.get("source_config_name")
                )

        except Exception as e:
            raise ClusterActionError(
                f"Unable to upload cluster config to the S3 bucket {self.bucket.name} due to exception: {e}"
            )

    def _upload_artifacts(self):
        """
        Upload cluster specific resources and cluster template.

        All dirs contained in resource dir will be uploaded as zip files to
        {bucket_name}/parallelcluster/clusters/{cluster_name}/{resource_dir}/artifacts.zip.
        All files contained in root dir will be uploaded to
        {bucket_name}/parallelcluster/clusters/{cluster_name}/{resource_dir}/artifact.
        """
        try:
            resources = pkg_resources.resource_filename(__name__, "../resources/custom_resources")
            self.bucket.upload_resources(
                resource_dir=resources, custom_artifacts_name=self._s3_artifacts_dict.get("custom_artifacts_name")
            )
            if self.config.scheduler_resources:
                self.bucket.upload_resources(
                    resource_dir=self.config.scheduler_resources,
                    custom_artifacts_name=self._s3_artifacts_dict.get("scheduler_resources_name"),
                )

            # Upload template
            if self.template_body:
                self.bucket.upload_cfn_template(self.template_body, self._s3_artifacts_dict.get("template_name"))

            # Fixme: the code doesn't work for awsbatch
            if isinstance(self.config.scheduling, SlurmScheduling):
                # upload instance types data
                self.bucket.upload_config(
                    self.config.get_instance_types_data(),
                    self._s3_artifacts_dict.get("instance_types_data_name"),
                    format=S3FileFormat.JSON,
                )
        except Exception as e:
            message = f"Unable to upload cluster resources to the S3 bucket {self.bucket.name} due to exception: {e}"
            LOGGER.error(message)
            raise ClusterActionError(message)

    def delete(self, keep_logs: bool = True):
        """Delete cluster preserving log groups."""
        try:
            if keep_logs:
                self._persist_cloudwatch_log_groups()
            self.stack.delete()
            self._terminate_nodes()
            self.__stack = ClusterStack(AWSApi.instance().cfn.describe_stack(self.stack_name))
        except Exception as e:
            self._terminate_nodes()
            raise ClusterActionError(f"Cluster {self.name} did not delete successfully. {e}")

    def _persist_cloudwatch_log_groups(self):
        """Enable cluster's CloudWatch log groups to persist past cluster deletion."""
        LOGGER.info("Configuring %s's CloudWatch log groups to persist past cluster deletion.", self.stack.name)
        log_group_keys = self._get_unretained_cw_log_group_resource_keys()
        if log_group_keys:  # Only persist the CloudWatch group
            self._persist_stack_resources(log_group_keys)

    def _get_unretained_cw_log_group_resource_keys(self):
        """Return the keys to all CloudWatch log group resources in template if the resource is not to be retained."""
        unretained_cw_log_group_keys = []
        for key, resource in self.stack.template.get("Resources", {}).items():
            if resource.get("Type") == "AWS::Logs::LogGroup" and resource.get("DeletionPolicy") != "Retain":
                unretained_cw_log_group_keys.append(key)
        return unretained_cw_log_group_keys

    def _persist_stack_resources(self, keys):
        """Set the resources in template identified by keys to have a DeletionPolicy of 'Retain'."""
        template = self.stack.template
        for key in keys:
            template["Resources"][key]["DeletionPolicy"] = "Retain"
        try:
            self.bucket.upload_cfn_template(template, self._s3_artifacts_dict.get("template_name"))
            self.stack.update_template(self.bucket.get_cfn_template_url(self._s3_artifacts_dict.get("template_name")))
        except AWSClientError as e:
            raise ClusterActionError(f"Unable to persist logs on cluster deletion, failed with error: {e}.")

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

            # validate target config
            self._validate_and_parse_config(suppress_validators, validation_failure_level, cluster_config)

            # verify changes
            patch = ConfigPatch(cluster=self, base_config=self.source_config, target_config=cluster_config)
            patch_allowed, update_changes = patch.check()
            if not (patch_allowed or force):
                raise ClusterActionError("Update failure", update_changes=update_changes)

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
                template_url=self.bucket.get_cfn_template_url(
                    template_name=self._s3_artifacts_dict.get("template_name")
                ),
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
