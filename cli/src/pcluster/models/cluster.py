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
import hashlib
import json
import logging
import os
import tempfile
import time
from copy import deepcopy
from datetime import datetime
from enum import Enum
from typing import List, Optional, Set, Tuple
from urllib.request import urlopen

import pkg_resources
from jinja2 import BaseLoader
from jinja2.sandbox import SandboxedEnvironment
from marshmallow import ValidationError

from pcluster.api.models import Metadata
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError, BadRequestError, LimitExceededError, StackNotFoundError, get_region
from pcluster.config.cluster_config import BaseClusterConfig, SchedulerPluginScheduling, SlurmScheduling, Tag
from pcluster.config.common import ValidatorSuppressor
from pcluster.config.config_patch import ConfigPatch
from pcluster.constants import (
    PCLUSTER_CLUSTER_NAME_TAG,
    PCLUSTER_NODE_TYPE_TAG,
    PCLUSTER_QUEUE_NAME_TAG,
    PCLUSTER_S3_ARTIFACTS_DICT,
    PCLUSTER_VERSION_TAG,
    STACK_EVENTS_LOG_STREAM_NAME_FORMAT,
)
from pcluster.models.cluster_resources import (
    ClusterInstance,
    ClusterStack,
    ExportClusterLogsFiltersParser,
    ListClusterLogsFiltersParser,
)
from pcluster.models.common import (
    BadRequest,
    CloudWatchLogsExporter,
    Conflict,
    LimitExceeded,
    LogStream,
    LogStreams,
    NotFound,
    create_logs_archive,
    export_stack_events,
    parse_config,
    upload_archive,
)
from pcluster.models.compute_fleet_status_manager import ComputeFleetStatus, ComputeFleetStatusManager
from pcluster.models.s3_bucket import S3Bucket, S3BucketFactory, S3FileFormat, create_s3_presigned_url, parse_bucket_url
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import (
    datetime_to_epoch,
    generate_random_name_with_prefix,
    get_attr,
    get_installed_version,
    grouper,
    yaml_load,
)
from pcluster.validators.common import FailureLevel, ValidationResult, ValidatorContext

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


class NotFoundClusterActionError(ClusterActionError, NotFound):
    """Represent an error if the cluster or an associated resource doesn't exist."""

    def __init__(self, message: str):
        super().__init__(message)


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
    elif isinstance(error, NotFound):
        return NotFoundClusterActionError(message)
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
        self.__official_ami = None
        self.__has_running_capacity = None
        self.__running_capacity = None

    @property
    def stack(self):
        """Return the ClusterStack object."""
        if not self.__stack:
            self.__stack = ClusterStack(AWSApi.instance().cfn.describe_stack(self.stack_name))
            self.__official_ami = self.__stack.official_ami
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

    @property
    def compute_fleet_status_manager(self) -> ComputeFleetStatusManager:
        """Return compute fleet status manager."""
        return ComputeFleetStatusManager.get_manager(self.name, self.stack.version, self.stack.scheduler)

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
        self._check_bucket_existence()
        try:
            return self.bucket.get_config(
                version_id=config_version, config_name=PCLUSTER_S3_ARTIFACTS_DICT.get("source_config_name")
            )
        except Exception as e:
            raise _cluster_error_mapper(
                e, f"Unable to load configuration from bucket '{self.bucket.name}/{self.s3_artifacts_dir}'.\n{e}"
            )

    def _check_bucket_existence(self):
        try:
            return self.bucket
        except Exception as e:
            raise _cluster_error_mapper(e, f"Unable to access bucket associated to the cluster.\n{e}")

    @property
    def config(self) -> BaseClusterConfig:
        """Return ClusterConfig object."""
        if not self.__config:
            try:
                self.__config = self._load_config(parse_config(self.source_config_text))
            except ConfigValidationError as exc:
                raise exc
            except Exception as e:
                raise _cluster_error_mapper(e, f"Unable to parse configuration file. {e}") from e
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
        status, _ = self.compute_fleet_status_with_last_updated_time
        return status

    @property
    def compute_fleet_status_with_last_updated_time(self) -> Tuple[ComputeFleetStatus, str]:
        """Status of the cluster compute fleet and the last compute fleet status updated time."""
        if self.stack.is_working_status or self.stack.status == "UPDATE_IN_PROGRESS":
            if self.stack.scheduler == "awsbatch":
                status = ComputeFleetStatus(
                    AWSApi.instance().batch.get_compute_environment_state(self.stack.batch_compute_environment)
                )
                last_updated_time = None
            else:
                status, last_updated_time = self.compute_fleet_status_manager.get_status_with_last_updated_time()
            return status, last_updated_time
        else:
            LOGGER.info(
                "stack %s is in status %s. Cannot retrieve compute fleet status.", self.stack_name, self.stack.status
            )
            return ComputeFleetStatus.UNKNOWN, None

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

            LOGGER.info("Generating artifact dir and uploading config...")
            self._add_tags()
            self._generate_artifact_dir()
            artifact_dir_generated = True
            self._upload_config()
            LOGGER.info("Generation and upload completed successfully")

            # Create template if not provided by the user
            if not (self.config.dev_settings and self.config.dev_settings.cluster_template):
                self.template_body = CDKTemplateBuilder().build_cluster_template(
                    cluster_config=self.config, bucket=self.bucket, stack_name=self.stack_name
                )

            LOGGER.info("Uploading cluster artifacts...")
            # upload cluster artifacts and generated template
            self._upload_artifacts()
            LOGGER.info("Upload of cluster artifacts completed successfully")

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

    def _load_config(self, cluster_config: dict) -> BaseClusterConfig:
        """Load the config and catch / translate any errors that occur during loading."""
        try:
            return ClusterSchema(cluster_name=self.name).load(cluster_config)
        except ValidationError as e:
            # syntactic failure
            data = str(sorted(e.messages.items()) if isinstance(e.messages, dict) else e)
            validation_failures = [ValidationResult(data, FailureLevel.ERROR, validator_type="ConfigSchemaValidator")]
            raise ConfigValidationError("Invalid cluster configuration.", validation_failures=validation_failures)

    def validate_create_request(self, validator_suppressors, validation_failure_level, dry_run=False):
        """Validate a create cluster request."""
        self._validate_no_existing_stack()
        self.config, ignored_validation_failures = self._validate_and_parse_config(
            validator_suppressors=validator_suppressors,
            validation_failure_level=validation_failure_level,
            context=ValidatorContext(),
        )
        if dry_run and isinstance(self.config.scheduling, SchedulerPluginScheduling):
            self._render_and_upload_scheduler_plugin_template(dry_run=dry_run)
        return ignored_validation_failures

    def _validate_no_existing_stack(self):
        if AWSApi.instance().cfn.stack_exists(self.stack_name):
            raise BadRequestClusterActionError(f"Cluster {self.name} already exists.")

    def _validate_and_parse_config(
        self, validator_suppressors, validation_failure_level, config_text=None, context: ValidatorContext = None
    ):
        """
        Perform syntactic and semantic validation and return parsed config.

        :param config_text: config to parse, self.source_config_text will be used if not specified.
        """
        cluster_config_dict = parse_config(config_text or self.source_config_text)

        try:
            LOGGER.info("Validating cluster configuration...")
            Cluster._load_additional_instance_type_data(cluster_config_dict)
            config = self._load_config(cluster_config_dict)
            config.official_ami = self.__official_ami

            validation_failures = config.validate(validator_suppressors, context)
            if any(f.level.value >= FailureLevel(validation_failure_level).value for f in validation_failures):
                raise ConfigValidationError("Invalid cluster configuration.", validation_failures=validation_failures)
            LOGGER.info("Validation succeeded.")
        except ConfigValidationError as e:
            raise e
        except Exception as e:
            raise ConfigValidationError(f"Invalid cluster configuration: {e}")

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
        self._check_bucket_existence()
        try:
            # Upload config with default values and sections
            if self.config:
                result = self.bucket.upload_config(
                    config=ClusterSchema(cluster_name=self.name).dump(deepcopy(self.config)),
                    config_name=PCLUSTER_S3_ARTIFACTS_DICT.get("config_name"),
                )

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

    def _upload_change_set(self, changes=None):
        """Upload change set."""
        if changes:
            self._check_bucket_existence()
            try:
                self.bucket.upload_config(
                    config=ConfigPatch.generate_json_change_set(changes),
                    config_name=PCLUSTER_S3_ARTIFACTS_DICT.get("change_set_name"),
                    format=S3FileFormat.JSON,
                )
            except Exception as e:
                message = (
                    f"Unable to upload cluster change set to the S3 bucket {self.bucket.name} due to exception: {e}"
                )
                LOGGER.error(message)
                raise _cluster_error_mapper(e, message)

    def _upload_artifacts(self):
        """
        Upload cluster specific resources and cluster template.

        All dirs contained in resource dir will be uploaded as zip files to
        {bucket_name}/parallelcluster/{version}/clusters/{cluster_name}/{resource_dir}/artifacts.zip.
        All files contained in root dir will be uploaded to
        {bucket_name}/parallelcluster/{version}/clusters/{cluster_name}/{resource_dir}/artifact.
        """
        LOGGER.info("Uploading cluster artifacts to S3...")
        self._check_bucket_existence()
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

            if isinstance(self.config.scheduling, (SlurmScheduling, SchedulerPluginScheduling)):
                # upload instance types data
                self.bucket.upload_config(
                    self.config.get_instance_types_data(),
                    PCLUSTER_S3_ARTIFACTS_DICT.get("instance_types_data_name"),
                    format=S3FileFormat.JSON,
                )

            if isinstance(self.config.scheduling, SchedulerPluginScheduling):
                self._render_and_upload_scheduler_plugin_template()
            LOGGER.info("Cluster artifacts uploaded correctly.")
        except BadRequestClusterActionError:
            raise
        except Exception as e:
            message = f"Unable to upload cluster resources to the S3 bucket {self.bucket.name} due to exception: {e}"
            LOGGER.error(message)
            raise _cluster_error_mapper(e, message)

    def _render_and_upload_scheduler_plugin_template(self, dry_run=False):
        scheduler_plugin_template = get_attr(
            self.config, "scheduling.settings.scheduler_definition.cluster_infrastructure.cloud_formation.template"
        )
        if not scheduler_plugin_template:
            return

        try:
            LOGGER.info("Downloading scheduler plugin CloudFormation template from %s", scheduler_plugin_template)
            if scheduler_plugin_template.startswith("s3"):
                bucket_parsing_result = parse_bucket_url(scheduler_plugin_template)
                result = AWSApi.instance().s3.get_object(
                    bucket_name=bucket_parsing_result["bucket_name"],
                    key=bucket_parsing_result["object_key"],
                    expected_bucket_owner=get_attr(
                        self.config,
                        "scheduling.settings.scheduler_definition.cluster_infrastructure.cloud_formation."
                        "s3_bucket_owner",
                    ),
                )
                file_content = result["Body"].read().decode("utf-8")
            else:
                with urlopen(  # nosec nosemgrep - scheduler_plugin_template url is properly validated
                    scheduler_plugin_template
                ) as f:
                    file_content = f.read().decode("utf-8")
        except Exception as e:
            raise BadRequestClusterActionError(
                f"Error while downloading scheduler plugin artifacts from '{scheduler_plugin_template}': {str(e)}"
            ) from e

        # checksum
        self.validate_scheduler_plugin_template_checksum(file_content, scheduler_plugin_template)

        # jinja rendering
        try:
            LOGGER.info("Rendering the following scheduler plugin CloudFormation template:\n%s", file_content)
            environment = SandboxedEnvironment(loader=BaseLoader)
            environment.filters["hash"] = (
                lambda value: hashlib.sha1(value.encode()).hexdigest()[0:16].capitalize()  # nosec nosemgrep
            )
            template = environment.from_string(file_content)
            rendered_template = template.render(
                cluster_configuration=ClusterSchema(cluster_name=self.name).dump(deepcopy(self.config)),
                cluster_name=self.name,
                instance_types_info=self.config.get_instance_types_data(),
            )
        except Exception as e:
            raise BadRequestClusterActionError(
                f"Error while rendering scheduler plugin template '{scheduler_plugin_template}': {str(e)}"
            ) from e
        if not dry_run:
            self.bucket.upload_cfn_template(
                rendered_template, PCLUSTER_S3_ARTIFACTS_DICT["scheduler_plugin_template_name"], S3FileFormat.TEXT
            )

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
            return yaml_load(AWSApi.instance().cfn.get_stack_template(self.stack_name))
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
            raise _cluster_error_mapper(e, f"Unable to delete running EC2 instances with error: {e}")

    @property
    def compute_instances(self) -> List[ClusterInstance]:
        """Get compute instances."""
        instances, _ = self.describe_instances(node_type=NodeType.COMPUTE)
        return instances

    @property
    def head_node_instance(self) -> ClusterInstance:
        """Get head node instance."""
        instances, _ = self.describe_instances(node_type=NodeType.HEAD_NODE)
        if instances:
            return instances[0]
        else:
            raise ClusterActionError("Unable to retrieve head node information.")

    def _get_instance_filters(self, node_type: NodeType, queue_name: str = None):
        filters = [
            {"Name": f"tag:{PCLUSTER_CLUSTER_NAME_TAG}", "Values": [self.stack_name]},
            {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
        ]
        if node_type:
            filters.append({"Name": f"tag:{PCLUSTER_NODE_TYPE_TAG}", "Values": [node_type.value]})
        if queue_name:
            filters.append({"Name": f"tag:{PCLUSTER_QUEUE_NAME_TAG}", "Values": [queue_name]})
        return filters

    def describe_instances(
        self, node_type: NodeType = None, next_token: str = None, queue_name: str = None
    ) -> Tuple[List[ClusterInstance], str]:
        """Return the cluster instances filtered by node type."""
        try:
            filters = self._get_instance_filters(node_type, queue_name)
            instances, token = AWSApi.instance().ec2.describe_instances(filters, next_token)
            return [ClusterInstance(instance) for instance in instances], token
        except AWSClientError as e:
            raise _cluster_error_mapper(e, f"Failed to retrieve cluster instances. {e}")

    def has_running_capacity(self, updated_value: bool = False) -> bool:
        """Return True if the cluster has running capacity. Note: the value will be cached."""
        if self.__has_running_capacity is None or updated_value:
            if self.stack.scheduler == "awsbatch":
                self.__has_running_capacity = self.get_running_capacity() > 0
            else:
                self.__has_running_capacity = (
                    self.compute_fleet_status_manager.get_status() != ComputeFleetStatus.STOPPED
                )
        return self.__has_running_capacity

    def get_running_capacity(self, updated_value: bool = False):
        """Return the number of instances or desired capacity. Note: the value will be cached."""
        if self.__running_capacity is None or updated_value:
            if self.stack.scheduler == "slurm":
                self.__running_capacity = len(self.compute_instances)
            elif self.stack.scheduler == "awsbatch":
                self.__running_capacity = AWSApi.instance().batch.get_compute_environment_capacity(
                    ce_name=self.stack.batch_compute_environment
                )
        return self.__running_capacity

    def start(self):
        """Start the cluster."""
        try:
            stack_status = self.stack.status
            if not self.stack.is_working_status:
                raise BadRequestClusterActionError(
                    f"Cannot start/enable compute fleet while stack is in {stack_status} status."
                )
            scheduler = self.config.scheduling.scheduler
            if scheduler == "awsbatch":
                self.enable_awsbatch_compute_environment()
            else:  # traditional scheduler
                self.start_compute_fleet()
        except ComputeFleetStatusManager.ConditionalStatusUpdateFailed:
            raise BadRequestClusterActionError(
                "Failed when starting compute fleet due to a concurrent update of the status. "
                "Please retry the operation."
            )
        except Exception as e:
            raise _cluster_error_mapper(e, f"Failed when starting compute fleet with error: {str(e)}")

    def start_compute_fleet(self):
        """Start compute fleet."""
        self.compute_fleet_status_manager.update_status(
            ComputeFleetStatus.START_REQUESTED, ComputeFleetStatus.STARTING, ComputeFleetStatus.RUNNING
        )

    def enable_awsbatch_compute_environment(self):
        """Enable AWS Batch compute environment."""
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

    def stop(self):
        """Stop compute fleet of the cluster."""
        try:
            stack_status = self.stack.status
            if not self.stack.is_working_status:
                raise BadRequestClusterActionError(
                    f"Cannot stop/disable compute fleet while stack is in {stack_status} status."
                )
            scheduler = self.config.scheduling.scheduler
            if scheduler == "awsbatch":
                self.disable_awsbatch_compute_environment()
            else:  # traditional scheduler
                self.stop_compute_fleet()
        except ComputeFleetStatusManager.ConditionalStatusUpdateFailed:
            raise BadRequestClusterActionError(
                "Failed when stopping compute fleet due to a concurrent update of the status. "
                "Please retry the operation."
            )
        except Exception as e:
            raise _cluster_error_mapper(e, f"Failed when stopping compute fleet with error: {str(e)}")

    def stop_compute_fleet(self):
        """Stop compute fleet."""
        self.compute_fleet_status_manager.update_status(
            ComputeFleetStatus.STOP_REQUESTED, ComputeFleetStatus.STOPPING, ComputeFleetStatus.STOPPED
        )

    def disable_awsbatch_compute_environment(self):
        """Disable AWS Batch compute environment."""
        LOGGER.info("Disabling AWS Batch compute environment : %s", self.name)
        try:
            AWSApi.instance().batch.disable_compute_environment(ce_name=self.stack.batch_compute_environment)
        except Exception as e:
            raise _cluster_error_mapper(e, f"Unable to disable Batch compute environment. {str(e)}")

    def validate_update_request(
        self,
        target_source_config: str,
        validator_suppressors: Set[ValidatorSuppressor] = None,
        validation_failure_level: FailureLevel = FailureLevel.ERROR,
        force: bool = False,
        dry_run: bool = False,
    ):
        """Validate a cluster update request."""
        self._validate_cluster_exists()
        self._validate_stack_status_not_in_progress()
        target_config, ignored_validation_failures = self._validate_and_parse_config(
            validator_suppressors=validator_suppressors,
            validation_failure_level=validation_failure_level,
            config_text=target_source_config,
            context=ValidatorContext(head_node_instance_id=self.head_node_instance.id),
        )
        changes = self._validate_patch(force, target_config)

        self._validate_scheduling_update(changes, target_config)

        if dry_run and isinstance(self.config.scheduling, SchedulerPluginScheduling):
            self._render_and_upload_scheduler_plugin_template(dry_run=dry_run)

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
            raise NotFoundClusterActionError(f"Cluster {self.name} does not exist.")

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

            self._add_tags()
            self._upload_config()
            self._upload_change_set(changes)

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

    def _add_tags(self):
        """Add tags PCLUSTER_CLUSTER_NAME_TAG and PCLUSTER_VERSION_TAG to the attribute config.tags."""
        if self.config.tags is None:
            self.config.tags = []

        # List of tags to be added to the cluster
        tags = {PCLUSTER_CLUSTER_NAME_TAG: self.name, PCLUSTER_VERSION_TAG: get_installed_version()}

        # Remove tags if they already exist
        self.config.tags = [tag for tag in self.config.tags if tag.key not in tags]

        # Add the tags
        self.config.tags += [Tag(key=tag_key, value=tag_value) for tag_key, tag_value in tags.items()]

    def _get_cfn_tags(self):
        """Return tag list in the format expected by CFN."""
        cluster_tags = [{"Key": tag.key, "Value": tag.value} for tag in self.config.tags]
        if self.config.scheduling.scheduler == "plugin":
            scheduler_plugin_tags = get_attr(self.config, "scheduling.settings.scheduler_definition.tags")
            if scheduler_plugin_tags:
                custom_scheduler_plugin_tags = [{"Key": tag.key, "Value": tag.value} for tag in scheduler_plugin_tags]
                cluster_tags += custom_scheduler_plugin_tags
        return cluster_tags

    def export_logs(
        self,
        bucket: str,
        bucket_prefix: str = None,
        keep_s3_objects: bool = False,
        start_time: datetime = None,
        end_time: datetime = None,
        filters: List[str] = None,
        output_file: str = None,
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
        :param filters: Filters in the format ["Name=name,Values=value1,value2"]
               Accepted filters are: private_dns_name, node_type==HeadNode
        """
        # check stack
        if not AWSApi.instance().cfn.stack_exists(self.stack_name):
            raise NotFoundClusterActionError(f"Cluster {self.name} does not exist.")

        try:
            with tempfile.TemporaryDirectory() as output_tempdir:
                # Create root folder for the archive
                archive_name = f"{self.name}-logs-{datetime.now().strftime('%Y%m%d%H%M')}"
                root_archive_dir = os.path.join(output_tempdir, archive_name)
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

                archive_path = create_logs_archive(root_archive_dir, output_file)
                if output_file:
                    return output_file
                else:
                    s3_path = upload_archive(bucket, bucket_prefix, archive_path)
                    return create_s3_presigned_url(s3_path)
        except Exception as e:
            raise ClusterActionError(f"Unexpected error when exporting cluster's logs: {e}")

    def _init_export_logs_filters(self, start_time, end_time, filters):
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
        return export_logs_filters

    def list_log_streams(self, filters: List[str] = None, next_token: str = None):
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
                raise NotFoundClusterActionError(f"Cluster {self.name} does not exist.")

            log_streams = []

            LOGGER.debug("Listing log streams from log group %s", self.stack.log_group_name)
            if self.stack.log_group_name:
                list_logs_filters = self._init_list_logs_filters(filters)
                log_stream_resp = AWSApi.instance().logs.describe_log_streams(
                    log_group_name=self.stack.log_group_name,
                    log_stream_name_prefix=list_logs_filters.log_stream_prefix,
                    next_token=next_token,
                )
                log_streams.extend(log_stream_resp["logStreams"])
                next_token = log_stream_resp.get("nextToken")
            else:
                LOGGER.debug("CloudWatch logging is not enabled for cluster %s.", self.name)
                raise BadRequestClusterActionError(f"CloudWatch logging is not enabled for cluster {self.name}.")

            return LogStreams(log_streams, next_token)

        except AWSClientError as e:
            raise _cluster_error_mapper(e, f"Unexpected error when retrieving cluster's logs: {e}")

    def _init_list_logs_filters(self, filters):
        head_node = None
        try:
            head_node = self.head_node_instance
        except ClusterActionError as e:
            LOGGER.debug(e)

        list_logs_filters = ListClusterLogsFiltersParser(
            head_node=head_node, log_group_name=self.stack.log_group_name, filters=filters
        )
        list_logs_filters.validate()
        return list_logs_filters

    def get_stack_events(self, next_token: str = None):
        """
        Get the CloudFormation stack events for the cluster.

        :param next_token Start from next_token if provided.
        """
        try:
            if not AWSApi.instance().cfn.stack_exists(self.stack_name):
                raise NotFoundClusterActionError(f"Cluster {self.name} does not exist.")
            return AWSApi.instance().cfn.get_stack_events(self.stack_name, next_token=next_token)
        except AWSClientError as e:
            raise _cluster_error_mapper(e, f"Unexpected error when retrieving stack events: {e}")

    def get_log_events(
        self,
        log_stream_name: str,
        start_time: datetime = None,
        end_time: datetime = None,
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
        if not AWSApi.instance().cfn.stack_exists(self.stack_name):
            raise NotFoundClusterActionError(f"Cluster {self.name} does not exist.")

        try:
            log_events_response = AWSApi.instance().logs.get_log_events(
                log_group_name=self.stack.log_group_name,
                log_stream_name=log_stream_name,
                end_time=datetime_to_epoch(end_time) if end_time else None,
                start_time=datetime_to_epoch(start_time) if start_time else None,
                limit=limit,
                start_from_head=start_from_head,
                next_token=next_token,
            )

            return LogStream(self.stack_name, log_stream_name, log_events_response)
        except AWSClientError as e:
            if e.message.startswith("The specified log group"):
                LOGGER.debug("Log Group %s doesn't exist.", self.stack.log_group_name)
                raise NotFoundClusterActionError(f"CloudWatch logging is not enabled for cluster {self.name}.")
            if e.message.startswith("The specified log stream"):
                LOGGER.debug("Log Stream %s doesn't exist.", log_stream_name)
                raise NotFoundClusterActionError(f"The specified log stream {log_stream_name} does not exist.")
            raise _cluster_error_mapper(e, f"Unexpected error when retrieving log events: {e}.")

    @property
    def _stack_events_stream_name(self):
        """Return the name of the stack events log stream."""
        return STACK_EVENTS_LOG_STREAM_NAME_FORMAT.format(self.stack_name)

    def _validate_scheduling_update(self, changes, target_config):
        """Update of Scheduling is not supported when SupportsClusterUpdate of the scheduler plugin is set to false."""
        # target_config.source_config.get("Scheduling") != self.config.source_config.get("Scheduling") doesn't mean
        # there's changes in the config, if queue list in the scheduling dict has different order, target_config dict
        # and original config dict may be different.
        if (
            self.config.scheduling.scheduler == "plugin"
            and get_attr(self.config, "scheduling.settings.scheduler_definition.requirements.supports_cluster_update")
            is False
            and target_config.source_config.get("Scheduling") != self.config.source_config.get("Scheduling")
        ):
            scheduling_changes = []
            # Example format of changes:
            # changes = [
            #     ["param_path", "parameter", "old value", "new value", "check", "reason", "action_needed"],
            #     [
            #         ["HeadNode", "Iam"],
            #         "AdditionalIamPolicies",
            #         None,
            #         {"Policy": "arn:aws:iam::aws:policy/FakePolicy"},
            #         "SUCCEEDED",
            #         "-",
            #         None,
            #     ],
            #     [
            #         ["HeadNode", "Iam"],
            #         "AdditionalIamPolicies",
            #         {"Policy": "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"},
            #         None,
            #         "SUCCEEDED",
            #         "-",
            #         None,
            #     ],
            #     [
            #         ["Scheduling", "SchedulerQueues[queue1]", "ComputeResources[compute-resource1]"],
            #         "InstanceType",
            #         "c5.2xlarge",
            #         "c5.xlarge",
            #         "SUCCEEDED",
            #         "-",
            #         None,
            #     ],
            # ]

            # The first element of changes is:
            # ["param_path", "parameter", "old value", "new value", "check", "reason", "action_needed"]
            for change in changes[1:]:
                if change[0][0] == "Scheduling":  # check if the param_path of the change start from Scheduling
                    scheduling_changes.append(change)
            if len(scheduling_changes) >= 1:
                raise ClusterUpdateError(
                    "Update failure: The scheduler plugin used for this cluster does not support updating the "
                    "scheduling configuration.",
                    [changes[0]] + scheduling_changes,
                )

    def validate_scheduler_plugin_template_checksum(self, file_content, scheduler_plugin_template):
        """Validate scheduler plugin template checksum match the expected checksum."""
        checksum = get_attr(
            self.config, "scheduling.settings.scheduler_definition.cluster_infrastructure.cloud_formation.checksum"
        )
        if checksum:
            actual_checksum = hashlib.sha256(file_content.encode()).hexdigest()
            if actual_checksum != checksum:
                raise BadRequestClusterActionError(
                    f"Error when validating scheduler plugin template '{scheduler_plugin_template}': "
                    f"checksum: {actual_checksum} does not match expected one: {checksum}"
                )

    def get_plugin_metadata(self):
        """Get the metadata name and version used for the response of DescribeCluster when the scheduler is plugin."""
        try:
            full_metadata = get_attr(self.config, "scheduling.settings.scheduler_definition.metadata")
            return (
                Metadata(name=full_metadata.get("Name"), version=full_metadata.get("Version"))
                if full_metadata
                else None
            )
        except ClusterActionError:
            LOGGER.warning("Unable to retrieve scheduler metadata from cluster configuration.")
            return None
