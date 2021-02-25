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

import pkg_resources
import yaml

from common.aws.aws_api import AWSApi
from common.aws.aws_resources import Stack, StackActionError
from common.boto3.common import AWSClientError
from pcluster.models.cluster_config import ClusterBucket, Tag
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import (
    NodeType,
    check_s3_bucket_exists,
    create_s3_bucket,
    generate_random_name_with_prefix,
    get_installed_version,
    get_stack_name,
    grouper,
    upload_resources_artifacts,
)

LOGGER = logging.getLogger(__name__)


class ClusterActionError(Exception):
    """Represent an error during the execution of an action on the cluster."""

    def __init__(self, message: str, validation_failures: list = None):
        super().__init__(message)
        self.validation_failures = validation_failures or []


class ClusterStack(Stack):
    """Class representing a running stack associated to a Cluster."""

    def __init__(self, name: str):
        """Init stack info."""
        super().__init__(name)

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

    def get_cluster_config(self):
        """Retrieve cluster config content."""
        if not self.s3_bucket_name:
            raise ClusterActionError("Unable to retrieve S3 Bucket name.")
        if not self.s3_artifact_directory:
            raise ClusterActionError("Unable to retrieve Artifact S3 Root Directory.")

        table_name = self.name
        config_version = None
        try:
            config_version_item = AWSApi().instance().dynamodb.get_item(table_name=table_name, key="CLUSTER_CONFIG")
            if config_version_item or "Item" in config_version_item:
                config_version = config_version_item["Item"].get("Version")
        except Exception:
            # Use latest if not found
            pass

        try:
            s3_object = (
                AWSApi()
                .instance()
                .s3.get_object(
                    bucket_name=self.s3_bucket_name,
                    key=f"{self.s3_artifact_directory}/configs/cluster-config.json",
                    version_id=config_version,
                )
            )
            config_content = s3_object["Body"].read().decode("utf-8")
            return yaml.safe_load(config_content)
        except Exception as e:
            raise ClusterActionError(
                f"Unable to load configuration from bucket '{self.s3_bucket_name}/{self.s3_artifact_directory}'.\n{e}"
            )

    def delete(self, keep_logs: bool = True):
        """Delete stack by preserving logs."""
        if keep_logs:
            self._persist_cloudwatch_log_groups()
        super().delete()

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


class Cluster:
    """Represent a running cluster, composed by a ClusterConfig and a ClusterStack."""

    def __init__(self, name: str, config: dict = None, stack: ClusterStack = None):
        self.name = name
        self.stack = stack
        self.bucket = None
        self.template_body = None
        self.config_version = None
        if config:
            self.config = ClusterSchema().load(config)
        else:
            try:
                self.stack = ClusterStack(self.stack_name)
            except StackActionError:
                raise ClusterActionError(f"Cluster {self.name} does not exist.")
            self.config = self.stack.get_cluster_config()

    @property
    def stack_name(self):
        """Return stack name."""
        return get_stack_name(self.name)

    def create(self, disable_rollback: bool = False):
        """Create cluster."""
        # check cluster existence
        if AWSApi.instance().cfn.stack_exists(self.stack_name):
            raise ClusterActionError(f"Cluster {self.name} already exists")

        validation_failures = self.config.validate()
        if validation_failures:
            # TODO skip validation errors
            raise ClusterActionError("Configuration is invalid", validation_failures=validation_failures)

        # Add tags information to the cluster
        version = get_installed_version()
        tags = self.config.tags or []
        tags.append(Tag(key="Version", value=version))
        tags = [{"Key": tag.key, "Value": tag.value} for tag in tags]

        # Create bucket if needed
        self._setup_cluster_bucket()

        creation_result = None
        try:
            # Create template if not provided by the user
            if not (self.config.dev_settings and self.config.dev_settings.cluster_template):
                self.template_body = CDKTemplateBuilder().build_cluster_template(
                    cluster_config=self.config, bucket=self.bucket
                )
                # print(yaml.dump(cluster.cluster_template_body))

            # upload cluster artifacts and generated template
            self._upload_artifacts()

            LOGGER.info("Creating stack named: %s", self.stack_name)
            creation_result = AWSApi.instance().cfn.create_stack(
                stack_name=self.stack_name,
                template_url=self.template_url,
                disable_rollback=disable_rollback,
                tags=tags,
            )

            self.stack = ClusterStack(self.stack_name)
            LOGGER.debug("StackId: %s", self.stack.id)
            LOGGER.info("Status: %s", self.stack.status)

        except Exception as e:
            LOGGER.critical(e)
            if not creation_result:
                # Cleanup S3 artifacts if stack is not created yet
                self.bucket.delete()
            raise ClusterActionError(f"Cluster creation failed.\n{e}")

    def _setup_cluster_bucket(self):
        """
        Create pcluster bucket, if needed, and attach info to the cluster itself.

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
                raise
        else:
            # Create 1 bucket per cluster named "parallelcluster-{random_string}" if bucket is not provided
            # This bucket needs to be removed on cluster deletion
            name = generate_random_name_with_prefix("parallelcluster")
            # self.cluster_s3_bucket = name
            remove_on_deletion = True
            LOGGER.debug("Creating S3 bucket for cluster resources, named %s", name)
            try:
                create_s3_bucket(name)
            except Exception:
                LOGGER.error("Unable to create S3 bucket %s.", name)
                raise

        # Use "{stack_name}-{random_string}" as directory in bucket
        artifact_directory = generate_random_name_with_prefix(self.stack_name)
        self.bucket = ClusterBucket(name, artifact_directory, remove_on_deletion)

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
                AWSApi().instance().s3.put_object(
                    bucket_name=self.bucket.name,
                    body=yaml.dump(self.template_body),
                    key=self._get_default_template_key(),
                )
            # Upload original config
            if self.config.source_config:
                result = (
                    AWSApi()
                    .instance()
                    .s3.put_object(
                        bucket_name=self.bucket.name,
                        body=yaml.dump(self.config.source_config),
                        key=self._get_config_key(),
                    )
                )
                # config version will be stored in DB by the cookbook at the first update
                self.config_version = result.get("VersionId")

        except Exception as e:
            raise ClusterActionError(
                f"Unable to upload cluster resources to the S3 bucket {self.bucket.name} due to exception: {e}"
            )

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
        return f"{self.bucket.artifact_directory}/configs/cluster-config.json"

    def delete(self, keep_logs: bool = True):
        """Delete cluster."""
        try:
            self.stack.delete(keep_logs)
            self._terminate_nodes()
        except Exception as e:
            self._terminate_nodes()
            raise ClusterActionError(f"Cluster deletion failed. Error: {e}")

    def _terminate_nodes(self):
        try:
            LOGGER.info("\nChecking if there are running compute nodes that require termination...")
            filters = [
                {"Name": "tag:Application", "Values": [self.stack_name]},
                {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
                {"Name": "tag:aws-parallelcluster-node-type", "Values": [str(NodeType.compute)]},
            ]
            instances = AWSApi().instance().ec2.list_instance_ids(filters)

            for instance_ids in grouper(instances, 100):
                LOGGER.info("Terminating following instances: %s", instance_ids)
                if instance_ids:
                    AWSApi().instance().ec2.terminate_instances(instance_ids)

            LOGGER.info("Compute fleet cleaned up.")
        except Exception as e:
            LOGGER.error("Failed when checking for running EC2 instances with error: %s", str(e))
