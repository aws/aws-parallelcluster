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
import os
import tempfile
import time
from copy import deepcopy
from datetime import datetime
from enum import Enum
from typing import List, Optional, Set, Tuple

import pkg_resources
import yaml
from dateutil.parser import parse
from marshmallow import ValidationError

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError, BadRequestError, LimitExceededError, StackNotFoundError, get_region
from pcluster.cli_commands.compute_fleet_status_manager import ComputeFleetStatus, ComputeFleetStatusManager
from pcluster.config.cluster_config import BaseClusterConfig, SlurmScheduling, Tag
from pcluster.config.common import ValidatorSuppressor
from pcluster.config.config_patch import ConfigPatch
from pcluster.constants import (
    PCLUSTER_CLUSTER_NAME_TAG,
    PCLUSTER_NODE_TYPE_TAG,
    PCLUSTER_S3_ARTIFACTS_DICT,
    PCLUSTER_VERSION_TAG,
    STACK_EVENTS_LOG_STREAM_NAME_FORMAT,
)
from pcluster.models.cluster_resources import (
    ClusterInstance,
    ClusterStack,
    ExportClusterLogsFiltersParser,
    FiltersParserError,
    ListClusterLogsFiltersParser,
)
from pcluster.models.common import (
    BadRequest,
    CloudWatchLogsExporter,
    Conflict,
    LimitExceeded,
    Logs,
    LogStream,
    create_logs_archive,
    export_stack_events,
    parse_config,
)
from pcluster.models.s3_bucket import S3Bucket, S3BucketFactory, S3FileFormat
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import generate_random_name_with_prefix, get_installed_version, grouper, isoformat_to_epoch
from pcluster.validators.cluster_validators import ClusterNameValidator
from pcluster.validators.common import FailureLevel, ValidationResult

# pylint: disable=C0302

LOGGER = logging.getLogger(__name__)

# pylint: disable=C0302


class NodeType(Enum):
    """Enum that identifies the cluster node type."""

    HEAD_NODE = "HeadNode"
    COMPUTE = "Compute"

    def __str__(self):
        return str(self.value)


class ClusterActionError(Exception):
    """Represent an error during the execution of an action on the cluster."""

    def __init__(self, message: str):
        super().__init__(message)


class ConfigValidationError(ClusterActionError):
    """Represent an error during the validation of the configuration."""

    def __init__(self, message: str, validation_failures: list = None):
        super().__init__(message)
        self.validation_failures = validation_failures or []


class ClusterUpdateError(ClusterActionError, BadRequest):
    """Represent an error during the update of the cluster."""

    def __init__(self, message: str, update_changes: list):
        super().__init__(message)
        self.update_changes = update_changes or []


class LimitExceededClusterActionError(ClusterActionError, LimitExceeded):
    """Represent an error during the execution of an action due to exceeding the limit of some AWS service."""

    def __init__(self, message: str):
        super().__init__(message)


class BadRequestClusterActionError(ClusterActionError, BadRequest):
    """Represent an error during the execution of an action due to a problem with the request."""

    def __init__(self, message: str):
        super().__init__(message)


class ConflictClusterActionError(ClusterActionError, Conflict):
    """Represent an error due to a conflict, such as a stack already existing, or being in the wrong state."""

    def __init__(self, message: str):
        super().__init__(message)


class NotFoundClusterActionError(ClusterActionError):
    """Represent an error if the cluster doesn't exist."""

    def __init__(self, name):
        super().__init__(f"Cluster {name} does not exist.")


def _cluster_error_mapper(error, message=None):
    if message is None:
        message = str(error)
    if isinstance(error, (LimitExceeded, LimitExceededError)):
        return LimitExceededClusterActionError(message)
    if isinstance(error, NotFoundClusterActionError):
        return NotFoundClusterActionError(message)
    elif isinstance(error, (BadRequest, BadRequestError)):
        return BadRequestClusterActionError(message)
    elif isinstance(error, Conflict):
        return ConflictClusterActionError(message)
    else:
        return ClusterActionError(message)


class Cluster:
    """Represent a running cluster, composed by a ClusterConfig and a ClusterStack."""

    def __init__(self, name: str, config: str = None, stack: ClusterStack = None):
        self.name = name
        self.__source_config_text = config
        self.__stack = stack
        self.__bucket = None
        self.template_body = None
        self.__config = None
        self.__s3_artifact_dir = None

        self.__has_running_capacity = None
        self.__running_capacity = None

    @property
    def stack(self):
        """Return the ClusterStack object."""
        if not self.__stack:
            self.__stack = ClusterStack(AWSApi.instance().cfn.describe_stack(self.stack_name))
        return self.__stack

    @property
    def source_config_text(self):
        """Return original config used to create the cluster."""
        if not self.__source_config_text:
            self.__source_config_text = self._get_cluster_config()
        return self.__source_config_text

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
            raise _cluster_error_mapper(
                e, f"Unable to find artifact dir in cluster stack {self.stack_name} output. {e}"
            )

    def _generate_artifact_dir(self):
        """
        Generate artifact directory in S3 bucket.

        cluster artifact dir is generated before cfn stack creation and only generate once.
        artifact_directory: e.g. parallelcluster/{version}/clusters/{cluster_name}-jfr4odbeonwb1w5k
        """
        service_directory = generate_random_name_with_prefix(self.name)
        self.__s3_artifact_dir = "/".join(
            [
                PCLUSTER_S3_ARTIFACTS_DICT.get("root_directory"),
                get_installed_version(),
                PCLUSTER_S3_ARTIFACTS_DICT.get("root_cluster_directory"),
                service_directory,
            ]
        )

    def _get_cluster_config(self):
        """Retrieve cluster config content."""
        config_version = self.stack.original_config_version
        try:
            return self.bucket.get_config(
                version_id=config_version, config_name=PCLUSTER_S3_ARTIFACTS_DICT.get("source_config_name")
            )
        except Exception as e:
            raise _cluster_error_mapper(
                e, f"Unable to load configuration from bucket '{self.bucket.name}/{self.s3_artifacts_dir}'.\n{e}"
            )

    @property
    def config(self) -> BaseClusterConfig:
        """Return ClusterConfig object."""
        if not self.__config:
            try:
                self.__config = ClusterSchema().load(parse_config(self.source_config_text))
            except Exception as e:
                raise _cluster_error_mapper(e, f"Unable to parse configuration file. {e}")
        return self.__config

    @config.setter
    def config(self, value):
        self.__config = value

    @property
    def config_presigned_url(self) -> str:
        """Return a pre-signed Url to download the config from the S3 bucket."""
        return self.bucket.get_config_presigned_url(
            config_name=PCLUSTER_S3_ARTIFACTS_DICT.get("source_config_name"),
            version_id=self.stack.original_config_version,
        )

    @property
    def compute_fleet_status(self) -> ComputeFleetStatus:
        """Status of the cluster compute fleet."""
        compute_fleet_status_manager = ComputeFleetStatusManager(self.name)
        status = compute_fleet_status_manager.get_status()
        if status == ComputeFleetStatus.UNKNOWN:
            stack_status_to_fleet_status = {
                "CREATE_IN_PROGRESS": ComputeFleetStatus.STARTING,
                "DELETE_IN_PROGRESS": ComputeFleetStatus.STOPPING,
                "CREATE_FAILED": ComputeFleetStatus.STOPPED,
                "ROLLBACK_IN_PROGRESS": ComputeFleetStatus.STOPPING,
                "ROLLBACK_FAILED": ComputeFleetStatus.STOPPED,
                "ROLLBACK_COMPLETE": ComputeFleetStatus.STOPPED,
                "DELETE_FAILED": ComputeFleetStatus.STOPPING,
            }
            return stack_status_to_fleet_status.get(self.status, status)
        return status

    @property
    def stack_name(self):
        """Return stack name."""
        return self.name

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

        if self.__source_config_text:
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
            raise _cluster_error_mapper(e, f"Unable to initialize s3 bucket. {e}")

        return self.__bucket

    def create(
        self,
        disable_rollback: bool = False,
        validator_suppressors: Set[ValidatorSuppressor] = None,
        validation_failure_level: FailureLevel = FailureLevel.ERROR,
    ) -> Tuple[Optional[str], List]:
        """
        Create cluster.

        raises ClusterActionError: in case of generic error
        raises ConfigValidationError: if configuration is invalid
        """
        creation_result = None
        artifact_dir_generated = False
        try:
            suppressed_validation_failures = self.validate_create_request(
                validator_suppressors, validation_failure_level
            )

            self._add_version_tag()
            self._generate_artifact_dir()
            artifact_dir_generated = True
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
                template_url=self.bucket.get_cfn_template_url(
                    template_name=PCLUSTER_S3_ARTIFACTS_DICT.get("template_name")
                ),
                disable_rollback=disable_rollback,
                tags=self._get_cfn_tags(),
            )

            return creation_result.get("StackId"), suppressed_validation_failures

        except ConfigValidationError as e:
            raise e
        except Exception as e:
            if not creation_result and artifact_dir_generated:
                # Cleanup S3 artifacts if stack is not created yet
                self.bucket.delete_s3_artifacts()
            raise _cluster_error_mapper(e, str(e))

    def validate_create_request(self, validator_suppressors, validation_failure_level):
        """Validate a create cluster request."""
        self._validate_no_existing_stack()
        self.config, ignored_validation_failures = self._validate_and_parse_config(
            validator_suppressors, validation_failure_level
        )
        return ignored_validation_failures

    def _validate_no_existing_stack(self):
        if AWSApi.instance().cfn.stack_exists(self.stack_name):
            raise BadRequestClusterActionError(f"cluster {self.name} already exists")

    def _validate_and_parse_config(self, validator_suppressors, validation_failure_level, config_text=None):
        """
        Perform syntactic and semantic validation and return parsed config.

        :param config_text: config to parse, self.source_config_text will be used if not specified.
        """
        cluster_config_dict = parse_config(config_text or self.source_config_text)

        try:
            LOGGER.info("Validating cluster configuration...")
            Cluster._load_additional_instance_type_data(cluster_config_dict)
            config = ClusterSchema().load(cluster_config_dict)

            validation_failures = ClusterNameValidator().execute(name=self.name)
            validation_failures += config.validate(validator_suppressors)
            for failure in validation_failures:
                if failure.level.value >= FailureLevel(validation_failure_level).value:
                    raise ConfigValidationError("Configuration is invalid", validation_failures=validation_failures)
            LOGGER.info("Validation succeeded.")
        except ValidationError as e:
            # syntactic failure
            ClusterSchema.process_validation_message(e)
            validation_failures = [
                ValidationResult(
                    str(sorted(e.messages.items())), FailureLevel.ERROR, validator_type="ConfigSchemaValidator"
                )
            ]
            raise ConfigValidationError("Configuration is invalid", validation_failures=validation_failures)
        except ConfigValidationError as e:
            raise e
        except Exception as e:
            raise ConfigValidationError(f"Configuration is invalid: {e}")

        return config, validation_failures

    @staticmethod
    def _load_additional_instance_type_data(cluster_config_dict):
        if "DevSettings" in cluster_config_dict:
            instance_types_data = cluster_config_dict["DevSettings"].get("InstanceTypesData")
            if instance_types_data:
                # Set additional instance types data in AWSApi. Schema load will use the information.
                AWSApi.instance().ec2.additional_instance_types_data = json.loads(instance_types_data)

    def _upload_config(self):
        """Upload source config and save config version."""
        try:
            # Upload config with default values and sections
            if self.config:
                result = self.bucket.upload_config(
                    config=ClusterSchema().dump(deepcopy(self.config)),
                    config_name=PCLUSTER_S3_ARTIFACTS_DICT.get("config_name"),
                )

                # config version will be stored in DB by the cookbook
                self.config.config_version = result.get("VersionId")

                # Upload original config
                result = self.bucket.upload_config(
                    config=self.source_config_text,
                    config_name=PCLUSTER_S3_ARTIFACTS_DICT.get("source_config_name"),
                    format=S3FileFormat.TEXT,
                )

                # original config version will be stored in CloudFormation Parameters
                self.config.original_config_version = result.get("VersionId")

        except Exception as e:
            raise _cluster_error_mapper(
                e, f"Unable to upload cluster config to the S3 bucket {self.bucket.name} due to exception: {e}"
            )

    def _upload_artifacts(self):
        """
        Upload cluster specific resources and cluster template.

        All dirs contained in resource dir will be uploaded as zip files to
        {bucket_name}/parallelcluster/{version}/clusters/{cluster_name}/{resource_dir}/artifacts.zip.
        All files contained in root dir will be uploaded to
        {bucket_name}/parallelcluster/{version}/clusters/{cluster_name}/{resource_dir}/artifact.
        """
        try:
            resources = pkg_resources.resource_filename(__name__, "../resources/custom_resources")
            self.bucket.upload_resources(
                resource_dir=resources, custom_artifacts_name=PCLUSTER_S3_ARTIFACTS_DICT.get("custom_artifacts_name")
            )
            if self.config.scheduler_resources:
                self.bucket.upload_resources(
                    resource_dir=self.config.scheduler_resources,
                    custom_artifacts_name=PCLUSTER_S3_ARTIFACTS_DICT.get("scheduler_resources_name"),
                )

            # Upload template
            if self.template_body:
                self.bucket.upload_cfn_template(self.template_body, PCLUSTER_S3_ARTIFACTS_DICT.get("template_name"))

            if isinstance(self.config.scheduling, SlurmScheduling):
                # upload instance types data
                self.bucket.upload_config(
                    self.config.get_instance_types_data(),
                    PCLUSTER_S3_ARTIFACTS_DICT.get("instance_types_data_name"),
                    format=S3FileFormat.JSON,
                )
        except Exception as e:
            message = f"Unable to upload cluster resources to the S3 bucket {self.bucket.name} due to exception: {e}"
            LOGGER.error(message)
            raise _cluster_error_mapper(e, message)

    def delete(self, keep_logs: bool = True):
        """Delete cluster preserving log groups."""
        try:
            if keep_logs:
                self._persist_cloudwatch_log_groups()
            self.stack.delete()
            self.__stack = ClusterStack(AWSApi.instance().cfn.describe_stack(self.stack_name))
        except StackNotFoundError:
            raise
        except Exception as e:
            self.terminate_nodes()
            raise _cluster_error_mapper(e, f"Cluster {self.name} did not delete successfully. {e}")

    def _persist_cloudwatch_log_groups(self):
        """Enable cluster's CloudWatch log groups to persist past cluster deletion."""
        LOGGER.info("Configuring %s's CloudWatch log groups to persist past cluster deletion.", self.stack.name)
        log_group_keys = self._get_unretained_cw_log_group_resource_keys()
        if log_group_keys:  # Only persist the CloudWatch group
            self._persist_stack_resources(log_group_keys)

    def _get_unretained_cw_log_group_resource_keys(self):
        """Return the keys to all CloudWatch log group resources in template if the resource is not to be retained."""
        unretained_cw_log_group_keys = []
        for key, resource in self._get_stack_template().get("Resources", {}).items():
            if resource.get("Type") == "AWS::Logs::LogGroup" and resource.get("DeletionPolicy") != "Retain":
                unretained_cw_log_group_keys.append(key)
        return unretained_cw_log_group_keys

    def _persist_stack_resources(self, keys):
        """Set the resources in template identified by keys to have a DeletionPolicy of 'Retain'."""
        template = self._get_stack_template()
        for key in keys:
            template["Resources"][key]["DeletionPolicy"] = "Retain"
        try:
            self.bucket.upload_cfn_template(template, PCLUSTER_S3_ARTIFACTS_DICT.get("template_name"))
            self._update_stack_template(
                self.bucket.get_cfn_template_url(PCLUSTER_S3_ARTIFACTS_DICT.get("template_name"))
            )
        except AWSClientError as e:
            raise _cluster_error_mapper(e, f"Unable to persist logs on cluster deletion, failed with error: {e}.")

    def _get_updated_stack_status(self):
        """Return updated status of the stack."""
        try:
            return AWSApi.instance().cfn.describe_stack(self.stack_name).get("StackStatus")
        except AWSClientError as e:
            raise _cluster_error_mapper(e, f"Unable to retrieve status of stack {self.stack_name}. {e}")

    def _update_stack_template(self, template_url):
        """Update template of the running stack according to updated template."""
        try:
            AWSApi.instance().cfn.update_stack_from_url(self.stack_name, template_url)
            self._wait_for_stack_update()
        except AWSClientError as e:
            if "no updates are to be performed" in str(e).lower():
                return  # If updated_template was the same as the stack's current one, consider the update a success
            raise e

    def _wait_for_stack_update(self):
        """Wait for the given stack to be finished updating."""
        while self._get_updated_stack_status() == "UPDATE_IN_PROGRESS":
            time.sleep(5)
        while self._get_updated_stack_status() == "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS":
            time.sleep(2)

    def _get_stack_template(self):
        """Return the template body of the stack."""
        try:
            return yaml.safe_load(AWSApi.instance().cfn.get_stack_template(self.stack_name))
        except AWSClientError as e:
            raise _cluster_error_mapper(e, f"Unable to retrieve template for stack {self.stack_name}. {e}")

    def terminate_nodes(self):
        """Terminate all compute nodes of a cluster."""
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
    def compute_instances(self) -> List[ClusterInstance]:
        """Get compute instances."""
        return [
            ClusterInstance(instance_data) for instance_data in self._describe_instances(node_type=NodeType.COMPUTE)
        ]

    @property
    def head_node_instance(self) -> ClusterInstance:
        """Get head node instance."""
        instances = self._describe_instances(node_type=NodeType.HEAD_NODE)
        if instances:
            return ClusterInstance(instances[0])
        else:
            raise ClusterActionError("Unable to retrieve head node information.")

    def _get_instance_filters(self, node_type: NodeType):
        return [
            {"Name": f"tag:{PCLUSTER_CLUSTER_NAME_TAG}", "Values": [self.stack_name]},
            {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
            {"Name": f"tag:{PCLUSTER_NODE_TYPE_TAG}", "Values": [node_type.value]},
        ]

    def _describe_instances(self, node_type: NodeType):
        """Return the cluster instances filtered by node type."""
        try:
            filters = self._get_instance_filters(node_type)
            return AWSApi.instance().ec2.describe_instances(filters)
        except AWSClientError as e:
            raise _cluster_error_mapper(e, f"Failed to retrieve cluster instances. {e}")

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
                    raise _cluster_error_mapper(e, f"Unable to enable Batch compute environment. {str(e)}")

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
            raise _cluster_error_mapper(e, f"Failed when starting compute fleet with error: {str(e)}")

    def stop(self):
        """Stop compute fleet of the cluster."""
        try:
            scheduler = self.config.scheduling.scheduler
            if scheduler == "awsbatch":
                LOGGER.info("Disabling AWS Batch compute environment : %s", self.name)
                try:
                    AWSApi.instance().batch.disable_compute_environment(ce_name=self.stack.batch_compute_environment)
                except Exception as e:
                    raise _cluster_error_mapper(e, f"Unable to disable Batch compute environment. {str(e)}")

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
            raise _cluster_error_mapper(e, f"Failed when stopping compute fleet with error: {str(e)}")

    def validate_update_request(
        self,
        target_source_config: str,
        validator_suppressors: Set[ValidatorSuppressor] = None,
        validation_failure_level: FailureLevel = FailureLevel.ERROR,
        force: bool = False,
    ):
        """Validate a cluster update request."""
        self._validate_cluster_exists()
        self._validate_stack_status_not_in_progress()
        target_config, ignored_validation_failures = self._validate_and_parse_config(
            validator_suppressors, validation_failure_level, target_source_config
        )
        changes = self._validate_patch(force, target_config)

        return target_config, changes, ignored_validation_failures

    def _validate_patch(self, force, target_config):
        patch = ConfigPatch(
            cluster=self, base_config=self.config.source_config, target_config=target_config.source_config
        )
        patch_allowed, update_changes = patch.check()
        if not (patch_allowed or force):
            raise ClusterUpdateError("Update failure", update_changes=update_changes)
        if len(update_changes) <= 1 and not force:
            raise BadRequestClusterActionError("No changes found in your cluster configuration.")

        return update_changes

    def _validate_stack_status_not_in_progress(self):
        if "IN_PROGRESS" in self.stack.status:
            raise ConflictClusterActionError(f"Cannot execute update while stack is in {self.stack.status} status.")

    def _validate_cluster_exists(self):
        if not AWSApi.instance().cfn.stack_exists(self.stack_name):
            raise NotFoundClusterActionError(self.name)

    def update(
        self,
        target_source_config: str,
        validator_suppressors: Set[ValidatorSuppressor] = None,
        validation_failure_level: FailureLevel = FailureLevel.ERROR,
        force: bool = False,
    ):
        """
        Update cluster.

        raises ClusterActionError: in case of generic error
        raises ConfigValidationError: if configuration is invalid
        raises ClusterUpdateError: if update is not allowed
        """
        try:
            target_config, changes, ignored_validation_failures = self.validate_update_request(
                target_source_config, validator_suppressors, validation_failure_level, force
            )

            self.config = target_config
            self.__source_config_text = target_source_config

            self._add_version_tag()
            self._upload_config()

            # Create template if not provided by the user
            if not (self.config.dev_settings and self.config.dev_settings.cluster_template):
                self.template_body = CDKTemplateBuilder().build_cluster_template(
                    cluster_config=self.config,
                    bucket=self.bucket,
                    stack_name=self.stack_name,
                    log_group_name=self.stack.log_group_name,
                )

            # upload cluster artifacts and generated template
            self._upload_artifacts()

            LOGGER.info("Updating stack named: %s", self.stack_name)
            AWSApi.instance().cfn.update_stack_from_url(
                stack_name=self.stack_name,
                template_url=self.bucket.get_cfn_template_url(
                    template_name=PCLUSTER_S3_ARTIFACTS_DICT.get("template_name")
                ),
                tags=self._get_cfn_tags(),
            )

            self.__stack = ClusterStack(AWSApi.instance().cfn.describe_stack(self.stack_name))
            LOGGER.debug("StackId: %s", self.stack.id)
            LOGGER.info("Status: %s", self.stack.status)

            return changes, ignored_validation_failures

        except ClusterActionError as e:
            # It can be a ConfigValidationError or ClusterUpdateError
            raise e
        except Exception as e:
            LOGGER.critical(e)
            raise _cluster_error_mapper(e, f"Cluster update failed.\n{e}")

    def _add_version_tag(self):
        """Add version tag to the stack."""
        if self.config.tags is None:
            self.config.tags = []
        # Remove PCLUSTER_VERSION_TAG if already exists
        self.config.tags = [tag for tag in self.config.tags if tag.key != PCLUSTER_VERSION_TAG]
        # Add PCLUSTER_VERSION_TAG
        self.config.tags.append(Tag(key=PCLUSTER_VERSION_TAG, value=get_installed_version()))

    def _get_cfn_tags(self):
        """Return tag list in the format expected by CFN."""
        return [{"Key": tag.key, "Value": tag.value} for tag in self.config.tags]

    def export_logs(
        self,
        output: str,
        bucket: str,
        bucket_prefix: str = None,
        keep_s3_objects: bool = False,
        start_time: str = None,
        end_time: str = None,
        filters: str = None,
    ):
        """
        Export cluster's logs in the given output path, by using given bucket as a temporary folder.

        :param output: file path to save log file archive to
        :param bucket: Temporary S3 bucket to be used to export cluster logs data
        :param bucket_prefix: Key path under which exported logs data will be stored in s3 bucket,
               also serves as top-level directory in resulting archive
        :param keep_s3_objects: Keep the exported objects exports to S3. The default behavior is to delete them
        :param start_time: Start time of interval of interest for log events. ISO 8601 format: YYYY-MM-DDThh:mm:ssTZD
        :param end_time: End time of interval of interest for log events. ISO 8601 format: YYYY-MM-DDThh:mm:ssTZD
        :param filters: Filters in the format Name=name,Values=value1,value2
               Accepted filters are: private_dns_name, node_type==HeadNode
        """
        # check stack
        if not AWSApi.instance().cfn.stack_exists(self.stack_name):
            raise ClusterActionError(f"Cluster {self.name} does not exist")

        try:
            with tempfile.TemporaryDirectory() as output_tempdir:
                # Create root folder for the archive
                root_archive_dir = os.path.join(
                    output_tempdir, f"{self.name}-logs-{datetime.now().strftime('%Y%m%d%H%M')}"
                )
                os.makedirs(root_archive_dir, exist_ok=True)

                if self.stack.log_group_name:
                    # Export logs from CloudWatch
                    export_logs_filters = self._init_export_logs_filters(start_time, end_time, filters)
                    logs_exporter = CloudWatchLogsExporter(
                        resource_id=self.name,
                        log_group_name=self.stack.log_group_name,
                        bucket=bucket,
                        output_dir=root_archive_dir,
                        bucket_prefix=bucket_prefix,
                        keep_s3_objects=keep_s3_objects,
                    )
                    logs_exporter.execute(
                        log_stream_prefix=export_logs_filters.log_stream_prefix,
                        start_time=export_logs_filters.start_time,
                        end_time=export_logs_filters.end_time,
                    )
                else:
                    LOGGER.debug(
                        "CloudWatch logging is not enabled for cluster %s, only CFN Stack events will be exported.",
                        {self.name},
                    )

                # Get stack events and write them into a file
                stack_events_file = os.path.join(root_archive_dir, self._stack_events_stream_name)
                export_stack_events(self.stack_name, stack_events_file)

                create_logs_archive(root_archive_dir, output)
        except Exception as e:
            raise ClusterActionError(f"Unexpected error when exporting cluster's logs: {e}")

    def _init_export_logs_filters(self, start_time, end_time, filters):
        try:
            head_node = None
            try:
                head_node = self.head_node_instance
            except ClusterActionError as e:
                LOGGER.debug(e)

            export_logs_filters = ExportClusterLogsFiltersParser(
                head_node=head_node,
                log_group_name=self.stack.log_group_name,
                start_time=start_time,
                end_time=end_time,
                filters=filters,
            )
            export_logs_filters.validate()
        except FiltersParserError as e:
            raise ClusterActionError(str(e))
        return export_logs_filters

    def list_logs(self, filters: str = None, next_token: str = None):
        """
        List cluster's logs.

        :param next_token: Token for paginated requests.
        :param filters: Filters in the format Name=name,Values=value1,value2
        Accepted filters are: private_dns_name, node_type==HeadNode
        :returns a dict with the structure {"logStreams": [], "stackEventsStream": {}}
        """
        try:
            # check stack
            if not AWSApi.instance().cfn.stack_exists(self.stack_name):
                raise ClusterActionError(f"Cluster {self.name} does not exist")

            LOGGER.debug("Listing log streams from log group %s", self.stack.log_group_name)
            cw_log_streams = None
            if self.stack.log_group_name:
                list_logs_filters = self._init_list_logs_filters(filters)
                cw_log_streams = AWSApi.instance().logs.describe_log_streams(
                    log_group_name=self.stack.log_group_name,
                    log_stream_name_prefix=list_logs_filters.log_stream_prefix,
                    next_token=next_token,
                )
            else:
                LOGGER.debug("CloudWatch logging is not enabled for cluster %s", self.name)

            stack_log_streams = None
            if not next_token:
                # add CFN Stack information only at the first request, when next-token is not specified
                stack_log_streams = [
                    {
                        "Stack Events Stream": self._stack_events_stream_name,
                        "Cluster Creation Time": parse(self.stack.creation_time).isoformat(timespec="seconds"),
                        "Last Update Time": parse(self.stack.last_updated_time).isoformat(timespec="seconds"),
                    }
                ]
            return Logs(stack_log_streams, cw_log_streams)

        except AWSClientError as e:
            raise _cluster_error_mapper(e, f"Unexpected error when retrieving cluster's logs: {e}")

    def _init_list_logs_filters(self, filters):
        try:
            head_node = None
            try:
                head_node = self.head_node_instance
            except ClusterActionError as e:
                LOGGER.debug(e)

            list_logs_filters = ListClusterLogsFiltersParser(
                head_node=head_node, log_group_name=self.stack.log_group_name, filters=filters
            )
            list_logs_filters.validate()
        except FiltersParserError as e:
            raise ClusterActionError(str(e))
        return list_logs_filters

    def get_log_events(
        self,
        log_stream_name: str,
        start_time: str = None,
        end_time: str = None,
        start_from_head: bool = False,
        limit: int = None,
        next_token: str = None,
    ):
        """
        Get the log stream events.

        :param log_stream_name: Log stream name
        :param start_time: Start time of interval of interest for log events. ISO 8601 format: YYYY-MM-DDThh:mm:ssTZD
        :param end_time: End time of interval of interest for log events. ISO 8601 format: YYYY-MM-DDThh:mm:ssTZD
        :param start_from_head: If the value is true, the earliest log events are returned first.
            If the value is false, the latest log events are returned first. The default value is false.
        :param limit: The maximum number of log events returned. If you don't specify a value,
            the maximum is as many log events as can fit in a response size of 1 MB, up to 10,000 log events.
        :param next_token: Token for paginated requests.
        """
        # check stack
        if not AWSApi.instance().cfn.stack_exists(self.stack_name):
            raise ClusterActionError(f"Cluster {self.name} does not exist")

        try:
            if log_stream_name != self._stack_events_stream_name:
                if not self.stack.log_group_name:
                    raise ClusterActionError(f"CloudWatch logging is not enabled for cluster {self.name}.")

                log_events_response = AWSApi.instance().logs.get_log_events(
                    log_group_name=self.stack.log_group_name,
                    log_stream_name=log_stream_name,
                    end_time=isoformat_to_epoch(end_time) if end_time else None,
                    start_time=isoformat_to_epoch(start_time) if start_time else None,
                    limit=limit,
                    start_from_head=start_from_head,
                    next_token=next_token,
                )
                return LogStream(self.stack_name, log_stream_name, log_events_response)
            else:
                stack_events = AWSApi.instance().cfn.get_stack_events(self.stack_name)
                stack_events.reverse()
                if limit:
                    if start_from_head:
                        stack_events = stack_events[:limit]
                    else:
                        stack_events = stack_events[len(stack_events) - limit :]  # noqa E203
                return LogStream(self.stack_name, log_stream_name, {"events": stack_events})
        except AWSClientError as e:
            raise _cluster_error_mapper(e, f"Unexpected error when retrieving log events: {e}")

    @property
    def _stack_events_stream_name(self):
        """Return the name of the stack events log stream."""
        return STACK_EVENTS_LOG_STREAM_NAME_FORMAT.format(self.stack_name)
