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
from abc import ABC
from enum import Enum
from typing import List

import yaml

from common.aws.aws_api import AWSApi
from common.boto3.common import AWSClientError
from pcluster.constants import PCLUSTER_S3_BUCKET_VERSION
from pcluster.utils import get_partition, get_region, zip_dir
from pcluster.validators.common import ValidationResult
from pcluster.validators.s3_validators import UrlValidator

LOGGER = logging.getLogger(__name__)


class Resource(ABC):
    """Represent an abstract Resource entity."""

    class Param:
        """
        Represent a Configuration-managed attribute of a Resource.

        Other than the value of the attribute, it contains metadata information that allows to check if the value is
        implied or not, get the update policy and the default value.
        Instances of this class are not meant to be created directly, but only through the `init_param` utility method
        of resource class.
        """

        def __init__(self, value, default=None, update_policy=None):

            # If the value is None, it means that the value has not been specified in the configuration; hence it can
            # be implied from its default, if present.
            if value is None and default is not None:
                self.__value = default
                self.__implied = True
            else:
                self.__value = value
                self.__implied = False
            self.__default = default
            self.__update_policy = update_policy

        @property
        def value(self):
            """
            Return the value of the parameter.

            This value is always kept in sync with the corresponding resource attribute, so it is always safe to read it
            from here, if needed.
            """
            return self.__value

        @property
        def implied(self):
            """Tell if the value of this parameter is implied or not."""
            return self.__implied

        @property
        def default(self):
            """Return the default value."""
            return self.__default

        @property
        def update_policy(self):
            """Return the update policy."""
            return self.__update_policy()

        def __repr__(self):
            return repr(self.value)

    def __init__(self, implied: bool = False):
        # Parameters registry
        self.__params = {}
        self._validation_failures: List[ValidationResult] = []
        self.implied = implied

    @property
    def params(self):
        """Return the params registry for this Resource."""
        return self.__params

    def get_param(self, param_name):
        """Get the information related to the specified parameter name."""
        return self.__params.get(param_name, None)

    def is_implied(self, param_name):
        """Tell if the value of an attribute is implied or not."""
        return self.__params[param_name].implied

    def __setattr__(self, key, value):
        """
        Override the parent __set_attr__ method to manage parameters information related to Resource attributes.

        When an attribute is initialized through the `init_param` method, a Resource.Param instance is associated to
        the attribute and then kept updated accordingly every time the attribute is updated.
        """
        if key != "_Resource__params":
            if isinstance(value, Resource.Param):
                # If value is a param instance, register the Param and replace the value in the attribute
                # Register in params dict
                self.__params[key] = value
                # Set parameter value as attribute value
                value = value.value
            else:
                # If other type, check if it is backed by a param; if yes, sync the param
                param = self.__params.get(key, None)
                if param:
                    param._Param__value = value
                    param._Param__implied = False

        super().__setattr__(key, value)

    @staticmethod
    def init_param(value, default=None, update_policy=None):
        """Create a resource attribute backed by a Configuration Parameter."""
        return Resource.Param(value, default=default, update_policy=update_policy)

    def validate(self) -> List[ValidationResult]:
        """Execute registered validators."""
        # Cleanup failures
        self._validation_failures.clear()

        # Call validators for nested resources
        for attr, value in self.__dict__.items():
            if isinstance(value, Resource):
                # Validate nested Resources
                self._validation_failures.extend(value.validate())
            if isinstance(value, list) and value:
                # Validate nested lists of Resources
                for item in self.__getattribute__(attr):
                    if isinstance(item, Resource):
                        self._validation_failures.extend(item.validate())

        # Update validators to be executed according to current status of the model and order by priority
        self._validate()
        return self._validation_failures

    def _validate(self):
        """
        Execute validators.

        Method to be implemented in Resources.
        """
        pass

    def _execute_validator(self, validator_class, **validator_args):
        """Execute the validator."""
        self._validation_failures.extend(validator_class().execute(**validator_args))
        return self._validation_failures

    def __repr__(self):
        """Return a human readable representation of the Resource object."""
        return "<{name}({attributes})>".format(
            name=self.__class__.__name__,
            attributes=",".join(f"{attr}={repr(value)}" for attr, value in self.__dict__.items()),
        )


# ------------ Common resources between ImageBuilder an Cluster models ----------- #


class BaseTag(Resource):
    """Represent the Tag configuration."""

    def __init__(self, key: str = None, value: str = None):
        super().__init__()
        self.key = Resource.init_param(key)
        self.value = Resource.init_param(value)


class Cookbook(Resource):
    """Represent the chef cookbook configuration."""

    def __init__(self, chef_cookbook: str = None, extra_chef_attributes: str = None):
        super().__init__()
        self.chef_cookbook = Resource.init_param(chef_cookbook)
        self.extra_chef_attributes = Resource.init_param(extra_chef_attributes)
        # TODO: add validator

    def _validate(self):
        self._execute_validator(UrlValidator, url=self.chef_cookbook)


class BaseDevSettings(Resource):
    """Represent the common dev settings configuration between the ImageBuilder and Cluster."""

    def __init__(self, cookbook: Cookbook = None, node_package: str = None, aws_batch_cli_package: str = None):
        super().__init__()
        self.cookbook = cookbook
        self.node_package = Resource.init_param(node_package)
        self.aws_batch_cli_package = Resource.init_param(aws_batch_cli_package)

    def _validate(self):
        if self.node_package:
            self._execute_validator(UrlValidator, url=self.node_package)
        if self.aws_batch_cli_package:
            self._execute_validator(UrlValidator, url=self.aws_batch_cli_package)


# ------------ Common attributes class between ImageBuilder an Cluster models ----------- #


class ExtraChefAttributes:
    """Extra Attributes for Chef Client."""

    def __init__(self, dev_settings: BaseDevSettings):
        self._cluster_attributes = {}
        self._extra_attributes = {}
        self._init_cluster_attributes(dev_settings)
        self._set_extra_attributes(dev_settings)

    def _init_cluster_attributes(self, dev_settings):
        if dev_settings and dev_settings.cookbook and dev_settings.cookbook.extra_chef_attributes:
            self._cluster_attributes = json.loads(dev_settings.cookbook.extra_chef_attributes).get("cluster") or {}

    def _set_extra_attributes(self, dev_settings):
        if dev_settings and dev_settings.cookbook and dev_settings.cookbook.extra_chef_attributes:
            self._extra_attributes = json.loads(dev_settings.cookbook.extra_chef_attributes)
            if "cluster" in self._extra_attributes:
                self._extra_attributes.pop("cluster")

    def dump_json(self):
        """Dump chef attribute json to string."""
        attribute_json = {"cluster": self._cluster_attributes}
        attribute_json.update(self._extra_attributes)
        return json.dumps(attribute_json, sort_keys=True)


class S3FileFormat(Enum):
    """Define S3 file format."""

    YAML = "yaml"
    JSON = "json"
    TEXT = "text"


class S3FileType(Enum):
    """Define S3 file types."""

    CONFIGS = "configs"
    TEMPLATES = "templates"
    CUSTOM_RESOURCES = "custom_resources"


class S3Bucket:
    """Represent the s3 bucket configuration."""

    def __init__(
        self,
        service_name: str,
        stack_name: str,
        artifact_directory: str,
        cleanup_on_deletion: bool = True,
        name: str = None,
        is_custom_bucket: bool = False,
    ):
        super().__init__()
        self._service_name = service_name
        self._stack_name = stack_name
        self._cleanup_on_deletion = cleanup_on_deletion
        self._root_directory = "parallelcluster"
        self._bootstrapped_file_name = ".bootstrapped"
        self.artifact_directory = artifact_directory
        self._is_custom_bucket = is_custom_bucket
        self.__partition = None
        self.__region = None
        self.__account_id = None
        self.__name = name

    @property
    def name(self):
        """Return bucket name."""
        if self.__name is None:
            self.__name = self.get_bucket_name(self.account_id, self.region)
        return self.__name

    @property
    def partition(self):
        """Return partition."""
        if self.__partition is None:
            self.__partition = get_partition()
        return self.__partition

    @property
    def region(self):
        """Return bucket region."""
        if self.__region is None:
            self.__region = get_region()
        return self.__region

    @property
    def account_id(self):
        """Return account id."""
        if self.__account_id is None:
            self.__account_id = AWSApi.instance().sts.get_account_id()
        return self.__account_id

    # --------------------------------------- S3 bucket utils --------------------------------------- #

    @staticmethod
    def get_bucket_name(account_id, region):
        """
        Get ParallelCluster bucket name.

        :param account_id
        :param region
        :return ParallelCluster bucket name e.g. parallelcluster-b9033160b61390ef-v1-do-not-delete
        """
        return "-".join(
            [
                "parallelcluster",
                S3Bucket.generate_s3_bucket_hash_suffix(account_id, region),
                PCLUSTER_S3_BUCKET_VERSION,
                "do",
                "not",
                "delete",
            ]
        )

    @staticmethod
    def generate_s3_bucket_hash_suffix(account_id, region):
        """
        Generate 16 characters hash suffix for ParallelCluster s3 bucket.

        :param account_id
        :param region
        :return: 16 chars string e.g. 2238a84ac8a74529
        """
        return hashlib.sha256((account_id + region).encode()).hexdigest()[0:16]

    def check_bucket_exists(self):
        """Check bucket existence by bucket name."""
        AWSApi.instance().s3.head_bucket(bucket_name=self.name)

    def create_bucket(self):
        """Create a new S3 bucket."""
        AWSApi.instance().s3.create_bucket(bucket_name=self.name, region=self.region)

    def configure_s3_bucket(self):
        """Configure s3 bucket to satisfy pcluster setting."""
        AWSApi.instance().s3.put_bucket_versioning(bucket_name=self.name, configuration={"Status": "Enabled"})
        AWSApi.instance().s3.put_bucket_encryption(
            bucket_name=self.name,
            configuration={"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
        )
        deny_http_policy = (
            '{{"Id":"DenyHTTP","Version":"2012-10-17","Statement":[{{"Sid":"AllowSSLRequestsOnly","Action":"s3:*",'
            '"Effect":"Deny","Resource":["arn:{partition}:s3:::{bucket_name}","arn:{partition}:s3:::{bucket_name}/*"],'
            '"Condition":{{"Bool":{{"aws:SecureTransport":"false"}}}},"Principal":"*"}}]}}'
        ).format(bucket_name=self.name, partition=self.partition)
        AWSApi.instance().s3.put_bucket_policy(bucket_name=self.name, policy=deny_http_policy)

    # --------------------------------------- S3 objects utils --------------------------------------- #

    def get_object_key(self, object_type, object_name):
        """Get object key of an artifact."""
        return "/".join([self.artifact_directory, object_type, object_name])

    def delete_s3_artifacts(self):
        """Cleanup S3 bucket artifact directory."""
        LOGGER.debug(
            "Cleaning up S3 resources bucket_name=%s, service_name=%s, remove_artifact=%s",
            self.name,
            self._service_name,
            self._cleanup_on_deletion,
        )
        if self.artifact_directory and self._cleanup_on_deletion:
            try:
                LOGGER.info("Deleting artifacts under %s/%s", self.name, self.artifact_directory)
                AWSApi.instance().s3_resource.delete_object(bucket_name=self.name, prefix=f"{self.artifact_directory}/")
                AWSApi.instance().s3_resource.delete_object_versions(
                    bucket_name=self.name, prefix=f"{self.artifact_directory}/"
                )
            except AWSClientError as e:
                LOGGER.warning(
                    "Failed to delete S3 artifact under %s/%s with error %s. Please delete them manually.",
                    self.name,
                    self.artifact_directory,
                    str(e),
                )

    def upload_bootstrapped_file(self):
        """Upload bootstrapped file to identify bucket is configured successfully."""
        AWSApi.instance().s3.put_object(
            bucket_name=self.name,
            body="bucket is configured successfully.",
            key="/".join([self._root_directory, self._bootstrapped_file_name]),
        )

    def check_bucket_is_bootstrapped(self):
        """Check bucket is configured successfully or not by bootstrapped file."""
        AWSApi.instance().s3.head_object(
            bucket_name=self.name, object_name="/".join([self._root_directory, self._bootstrapped_file_name])
        )

    def upload_config(self, config, config_name, format=S3FileFormat.YAML):
        """Upload config file to S3 bucket."""
        return self._upload_file(
            file_type=S3FileType.CONFIGS.value, content=config, file_name=config_name, format=format
        )

    def upload_cfn_template(self, template_body, template_name, format=S3FileFormat.YAML):
        """Upload cloudformation template to S3 bucket."""
        return self._upload_file(
            file_type=S3FileType.TEMPLATES.value, content=template_body, file_name=template_name, format=format
        )

    def upload_resources(self, resource_dir, custom_artifacts_name):
        """
        Upload custom resources to S3 bucket.

        All dirs contained in resource dir will be uploaded as zip files to
        {bucket_name}/parallelcluster/clusters/{cluster_name}/{resource_dir}/artifacts.zip.
        or {bucket_name}/parallelcluster/imagebuilders/{image_name}/{resource_dir}/artifacts.zip.
        All files contained in root dir will be uploaded to
        {bucket_name}/parallelcluster/clusters/{cluster_name}/{resource_dir}/artifact.
        or {bucket_name}/parallelcluster/imagebuilders/{image_name}/{resource_dir}/artifacts
        :param resource_dir: resource directory containing the resources to upload.
        :param custom_artifacts_name: custom_artifacts_name for zipped dir
        """
        for res in os.listdir(resource_dir):
            path = os.path.join(resource_dir, res)
            if os.path.isdir(path):
                AWSApi.instance().s3.upload_fileobj(
                    file_obj=zip_dir(os.path.join(resource_dir, res)),
                    bucket_name=self.name,
                    key=self.get_object_key(S3FileType.CUSTOM_RESOURCES.value, custom_artifacts_name),
                )
            elif os.path.isfile(path):
                AWSApi.instance().s3.upload_file(
                    file_path=os.path.join(resource_dir, res),
                    bucket_name=self.name,
                    key=self.get_object_key(S3FileType.CUSTOM_RESOURCES.value, res),
                )

    def get_config(self, config_name, version_id=None, format=S3FileFormat.YAML):
        """Get config file from S3 bucket."""
        return self._get_file(
            file_type=S3FileType.CONFIGS.value, file_name=config_name, version_id=version_id, format=format
        )

    def get_config_url(self, config_name):
        """Get config file http url from S3 bucket."""
        return self._get_file_url(file_name=config_name, file_type=S3FileType.CONFIGS.value)

    def get_cfn_template(self, template_name, version_id=None, format=S3FileFormat.YAML):
        """Get cfn template from S3 bucket."""
        return self._get_file(
            file_type=S3FileType.TEMPLATES.value, file_name=template_name, version_id=version_id, format=format
        )

    def get_cfn_template_url(self, template_name):
        """Get cfn template http url from S3 bucket."""
        return self._get_file_url(file_type=S3FileType.TEMPLATES.value, file_name=template_name)

    def get_resource_url(self, resource_name):
        """Get custom resource http url from S3 bucket."""
        return self._get_file_url(file_type=S3FileType.CUSTOM_RESOURCES.value, file_name=resource_name)

    # --------------------------------------- S3 private functions --------------------------------------- #

    def _upload_file(self, content, file_name, file_type, format=S3FileFormat.YAML):
        """Upload file to S3 bucket."""
        if format == S3FileFormat.YAML:
            result = AWSApi.instance().s3.put_object(
                bucket_name=self.name,
                body=yaml.dump(content),
                key=self.get_object_key(file_type, file_name),
            )
        elif format == S3FileFormat.JSON:
            result = AWSApi.instance().s3.put_object(
                bucket_name=self.name,
                body=json.dumps(content),
                key=self.get_object_key(file_type, file_name),
            )
        else:
            result = AWSApi.instance().s3.put_object(
                bucket_name=self.name,
                body=content,
                key=self.get_object_key(file_type, file_name),
            )
        return result

    def _get_file(self, file_name, file_type, version_id=None, format=S3FileFormat.YAML):
        """Get file from S3 bucket."""
        result = AWSApi.instance().s3.get_object(
            bucket_name=self.name, key=self.get_object_key(file_type, file_name), version_id=version_id
        )

        file_content = result["Body"].read().decode("utf-8")

        if format == S3FileFormat.YAML:
            file = yaml.safe_load(file_content)
        elif format == S3FileFormat.JSON:
            file = json.loads(file_content)
        else:
            file = file_content
        return file

    def _get_file_url(self, file_name, file_type):
        """Get file url from S3 bucket."""
        url = "https://{bucket_name}.s3.{region}.amazonaws.com{partition_suffix}/{config_key}".format(
            bucket_name=self.name,
            region=self.region,
            partition_suffix=".cn" if self.region.startswith("cn") else "",
            config_key=self.get_object_key(file_type, file_name),
        )
        return url


class S3BucketFactory:
    """S3 bucket factory to return a bucket object with existence check and creation."""

    @classmethod
    def init_s3_bucket(cls, service_name: str, artifact_directory: str, stack_name: str, custom_s3_bucket: str):
        """Initialize the s3 bucket."""
        if custom_s3_bucket:
            bucket = cls._check_custom_bucket(service_name, custom_s3_bucket, artifact_directory, stack_name)
        else:
            bucket = cls._check_default_bucket(service_name, artifact_directory, stack_name)

        return bucket

    @classmethod
    def _check_custom_bucket(cls, service_name: str, custom_s3_bucket: str, artifact_directory: str, stack_name: str):
        bucket = S3Bucket(
            service_name=service_name,
            name=custom_s3_bucket,
            artifact_directory=artifact_directory,
            stack_name=stack_name,
            is_custom_bucket=True,
        )
        try:
            bucket.check_bucket_exists()
        except AWSClientError as e:
            raise AWSClientError(
                "check_bucket_exists", f"Unable to access config-specified S3 bucket {bucket.name}. Due to {str(e)}"
            )

        return bucket

    @classmethod
    def _check_default_bucket(cls, service_name: str, artifact_directory: str, stack_name: str):
        bucket = S3Bucket(service_name=service_name, artifact_directory=artifact_directory, stack_name=stack_name)
        try:
            bucket.check_bucket_exists()
        except AWSClientError as e:
            cls._create_bucket(bucket, e)

        try:
            bucket.check_bucket_is_bootstrapped()
        except AWSClientError as e:
            cls._configure_bucket(bucket, e)

        return bucket

    @classmethod
    def _create_bucket(cls, bucket: S3Bucket, e: AWSClientError):
        if e.error_code == "404":
            try:
                bucket.create_bucket()
            except AWSClientError as error:
                LOGGER.error("Unable to create S3 bucket %s.", bucket.name)
                raise error
        else:
            LOGGER.error("Unable to check S3 bucket %s existence.", bucket.name)
            raise e

    @classmethod
    def _configure_bucket(cls, bucket: S3Bucket, e: AWSClientError):
        if e.error_code == "404":
            try:
                bucket.configure_s3_bucket()
                bucket.upload_bootstrapped_file()
            except AWSClientError as error:
                LOGGER.error("Configure S3 bucket %s failed.", bucket.name)
                raise error
        else:
            LOGGER.error("Unable to check S3 bucket %s is configured properly.", bucket.name)
            raise e
