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
import copy
import logging
import re

from common.aws.aws_api import AWSApi
from common.aws.aws_resources import StackInfo
from common.boto3.common import AWSClientError, ImageNotFoundError
from common.imagebuilder_utils import AMI_NAME_REQUIRED_SUBSTRING, search_tag
from pcluster.constants import PCLUSTER_S3_BUCKET_TAG, PCLUSTER_S3_IMAGE_DIR_TAG
from pcluster.models.common import BaseTag, S3Bucket, S3BucketFactory
from pcluster.schemas.imagebuilder_schema import ImageBuilderSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import generate_random_name_with_prefix, get_installed_version, get_region
from pcluster.validators.common import FailureLevel

ImageBuilderStatusMapping = {
    "BUILD_IN_PROGRESS": [
        "CREATE_IN_PROGRESS",
        "ROLLBACK_IN_PROGRESS",
        "UPDATE_IN_PROGRESS",
        "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
        "UPDATE_ROLLBACK_IN_PROGRESS",
        "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS",
        "REVIEW_IN_PROGRESS",
        "IMPORT_IN_PROGRESS",
        "IMPORT_ROLLBACK_IN_PROGRESS",
    ],
    "BUILD_FAILED": [
        "CREATE_FAILED",
        "ROLLBACK_FAILED",
        "ROLLBACK_COMPLETE",
        "UPDATE_ROLLBACK_FAILED",
        "UPDATE_ROLLBACK_COMPLETE",
        "IMPORT_ROLLBACK_FAILED",
        "IMPORT_ROLLBACK_COMPLETE",
    ],
    "BUILD_COMPLETE": ["CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"],
    "DELETE_IN_PROGRESS": ["DELETE_IN_PROGRESS"],
    "DELETE_FAILED": ["DELETE_FAILED"],
    "DELETE_COMPLETE": ["DELETE_COMPLETE"],
}

LOGGER = logging.getLogger(__name__)


class ImageBuilderActionError(Exception):
    """Represent an error during the execution of an action on the imagebuilder."""

    def __init__(self, message: str, validation_failures: list = None):
        super().__init__(message)
        self.validation_failures = validation_failures or []


class ImageBuilderStack(StackInfo):
    """Class representing a running stack associated to a building image."""

    def __init__(self, stack_data: dict):
        """Init stack info."""
        super().__init__(stack_data)
        try:
            self._image_resource = AWSApi.instance().cfn.describe_stack_resource(self.name, "ParallelClusterImage")
        except AWSClientError:
            self._image_resource = None

    @property
    def s3_bucket_name(self):
        """Return the name of the bucket used to store image information."""
        return self._get_tag(PCLUSTER_S3_BUCKET_TAG)

    @property
    def s3_artifact_directory(self):
        """Return the artifact directory of the bucket used to store image information."""
        return self._get_tag(PCLUSTER_S3_IMAGE_DIR_TAG)

    @property
    def version(self):
        """Return the version of ParallelCluster used to create the stack."""
        return self._get_tag("pcluster_version")

    @property
    def image_id(self):
        """Return output image id."""
        if self._image_resource:
            try:
                image_build_version_arn = self._image_resource.get("StackResourceDetail").get("PhysicalResourceId")
                return AWSApi.instance().imagebuilder.get_image_id(image_build_version_arn)
            except (AWSClientError, KeyError):
                return None
        return None


class ImageBuilder:
    """Represent a building image, composed by an ImageBuilder config and an ImageBuilderStack."""

    def __init__(self, image_name: str, config: dict = None, stack: ImageBuilderStack = None):
        self.image_name = image_name
        self.__source_config = config
        self.__stack = stack
        self.__config = None
        self.__bucket = None
        self.template_body = None
        self._s3_artifacts_dict = {
            "root_directory": "parallelcluster",
            "root_image_directory": "imagebuilders",
            "source_config_name": "image-config-original.yaml",
            "config_name": "image-config.yaml",
            "template_name": "aws-parallelcluster-imagebuilder.cfn.yaml",
        }
        self.__s3_artifact_dir = None

    @property
    def s3_artifacts_dir(self):
        """Get s3 artifacts dir."""
        if self.__s3_artifact_dir is None:
            self._get_artifact_dir()
        return self.__s3_artifact_dir

    @property
    def stack(self):
        """Return the ImageBuilderStack object."""
        if not self.__stack:
            try:
                self.__stack = ImageBuilderStack(AWSApi().instance().cfn.describe_stack(self.image_name))
            except AWSClientError:
                raise ImageBuilderActionError(f"ImageBuilder stack {self.image_name} does not exist.")
        return self.__stack

    @property
    def source_config(self):
        """Return config used to create the imagebuilder stack."""
        if not self.__source_config:
            try:
                self.__source_config = self.bucket.get_config(config_name=self._s3_artifacts_dict.get("config_name"))
            except Exception as e:
                raise ImageBuilderActionError(
                    "Unable to load configuration from bucket " f"'{self.bucket.name}/{self.s3_artifacts_dir}'.\n{e}"
                )
        return self.__source_config

    @property
    def imagebuild_status(self):
        """Return the status of the stack of build image process."""
        cfn_status = self.stack.status
        for key, value in ImageBuilderStatusMapping.items():
            if cfn_status in value:
                return key
        return None

    @property
    def config(self):
        """Return ImageBuilder Config object."""
        if not self.__config:
            self.__config = ImageBuilderSchema().load(self.source_config)
        return self.__config

    @property
    def bucket(self):
        """Return a bucket configuration."""
        if self.__bucket:
            return self.__bucket

        if self.__source_config:
            custom_bucket_name = self.config.custom_s3_bucket
        else:
            custom_bucket_name = self._get_custom_bucket()

        self.__bucket = S3BucketFactory.init_s3_bucket(
            service_name=self.image_name,
            stack_name=self.image_name,
            custom_s3_bucket=custom_bucket_name,
            artifact_directory=self.s3_artifacts_dir,
        )
        return self.__bucket

    def _get_custom_bucket(self):
        """Try to get custom bucket name from image tag or stack tag."""
        custom_bucket_name = None
        try:
            image_info = AWSApi.instance().ec2.describe_image_by_name_tag(self.image_name)
            custom_bucket_name = search_tag(image_info, PCLUSTER_S3_BUCKET_TAG)
        except AWSClientError as e:
            if not isinstance(e, ImageNotFoundError):
                raise ImageBuilderActionError(f"Unable to get S3 bucket name from image {self.image_name} tag. {e}")

        if custom_bucket_name is None:
            try:
                custom_bucket_name = self.stack.s3_bucket_name
            except AWSClientError as e:
                raise ImageBuilderActionError(f"Unable to get S3 bucket name from stack {self.stack.name} tag. {e}")

        return (
            custom_bucket_name
            if custom_bucket_name != S3Bucket.get_bucket_name(AWSApi.instance().sts.get_account_id(), get_region())
            else None
        )

    def _get_artifact_dir(self):
        """Get artifact directory from image tag or stack tag."""
        try:
            image_info = AWSApi.instance().ec2.describe_image_by_name_tag(self.image_name)
            self.__s3_artifact_dir = search_tag(image_info, PCLUSTER_S3_IMAGE_DIR_TAG)
            if self.__s3_artifact_dir is None:
                raise ImageNotFoundError
        except AWSClientError as e:
            if not isinstance(e, ImageNotFoundError):
                LOGGER.error("Unable to find tag %s in image %s.", PCLUSTER_S3_IMAGE_DIR_TAG, self.image_name)
                raise ImageBuilderActionError(f"Unable to get artifact directory from image {self.image_name} tag. {e}")

        try:
            self.__s3_artifact_dir = self.stack.s3_artifact_directory

            if self.__s3_artifact_dir is None:
                raise AWSClientError(
                    function_name="_get_artifact_dir",
                    message="No artifact directory found in image tag and cloudformation stack tag.",
                )
        except AWSClientError as e:
            LOGGER.error("No artifact directory found in image tag and cloudformation stack tag.")
            raise ImageBuilderActionError(
                f"Unable to get artifact directory from image {self.image_name} tag and cloudformation stack tag. {e}"
            )

    def _generate_artifact_dir(self):
        """
        Generate artifact directory in S3 bucket.

        Image artifact dir is generated before cfn stack creation and only generate once.
        artifact_directory: e.g. parallelcluster/imagebuilders/{image_name}-jfr4odbeonwb1w5k
        """
        service_directory = generate_random_name_with_prefix(self.image_name)
        self.__s3_artifact_dir = "/".join(
            [
                self._s3_artifacts_dict.get("root_directory"),
                self._s3_artifacts_dict.get("root_image_directory"),
                service_directory,
            ]
        )

    def create(
        self,
        disable_rollback: bool = True,
        suppress_validators: bool = False,
        validation_failure_level: FailureLevel = FailureLevel.ERROR,
    ):
        """Create the CFN Stack and associate resources."""
        # validate image name
        self._validate_image_name()

        # check image existence
        if AWSApi.instance().ec2.image_exists(self.image_name):
            raise ImageBuilderActionError(f"ParallelCluster image {self.image_name} already exists")

        # check stack existence
        if AWSApi.instance().cfn.stack_exists(self.image_name):
            raise ImageBuilderActionError(
                f"ParallelCluster build infrastructure for image {self.image_name} already exists"
            )

        if not suppress_validators:
            validation_failures = self.config.validate()
            for failure in validation_failures:
                if failure.level.value >= FailureLevel(validation_failure_level).value:
                    # Raise the exception if there is a failure with a level equals to or greater than the specified one
                    raise ImageBuilderActionError("Configuration is invalid", validation_failures=validation_failures)

        # Generate artifact directory for image
        self._generate_artifact_dir()

        # Add tags information to the stack
        cfn_tags = copy.deepcopy(self.config.build.tags) or []
        cfn_tags.append(BaseTag(key="pcluster_build_image", value=get_installed_version()))
        cfn_tags.append(BaseTag(key=PCLUSTER_S3_BUCKET_TAG, value=self.bucket.name))
        cfn_tags.append(BaseTag(key=PCLUSTER_S3_IMAGE_DIR_TAG, value=self.s3_artifacts_dir))
        # TODO add tags for build log
        cfn_tags = [{"Key": tag.key, "Value": tag.value} for tag in cfn_tags]

        creation_result = None
        try:
            self._upload_config()

            LOGGER.info("Building ParallelCluster image named: %s", self.image_name)

            # Generate cdk cfn template
            self.template_body = CDKTemplateBuilder().build_imagebuilder_template(
                image_config=self.config, image_name=self.image_name, bucket=self.bucket
            )

            # upload generated template
            self._upload_artifacts()

            # Stack creation
            creation_result = AWSApi.instance().cfn.create_stack_from_url(
                stack_name=self.image_name,
                template_url=self.bucket.get_cfn_template_url(
                    template_name=self._s3_artifacts_dict.get("template_name")
                ),
                disable_rollback=disable_rollback,
                tags=cfn_tags,
            )

            self.__stack = ImageBuilderStack(AWSApi().instance().cfn.describe_stack(self.image_name))
            LOGGER.debug("StackId: %s", self.stack.id)
            LOGGER.info("Status: %s", self.stack.status)

        except Exception as e:
            LOGGER.critical(e)
            if not creation_result:
                # Cleanup S3 artifacts if stack is not created yet
                self.bucket.delete_s3_artifacts()
            raise ImageBuilderActionError(f"ParallelCluster image build infrastructure creation failed.\n{e}")

    def _upload_config(self):
        """Upload source config to S3 bucket."""
        try:
            if self.config:
                # Upload config with default values
                self.bucket.upload_config(config=self.config, config_name=self._s3_artifacts_dict.get("config_name"))

                # Upload original config
                self.bucket.upload_config(
                    config=self.config.source_config, config_name=self._s3_artifacts_dict.get("source_config_name")
                )

        except Exception as e:
            raise ImageBuilderActionError(
                f"Unable to upload imagebuilder config to the S3 bucket {self.bucket.name} due to exception: {e}"
            )

    def _upload_artifacts(self):
        """Upload  artifacts to S3 bucket."""
        try:
            if self.template_body:
                # upload cfn template
                self.bucket.upload_cfn_template(self.template_body, self._s3_artifacts_dict.get("template_name"))
        except Exception as e:
            raise ImageBuilderActionError(
                f"Unable to upload imagebuilder cfn template to the S3 bucket {self.bucket.name} due to exception: {e}"
            )

    def _validate_image_name(self):
        match = re.match(r"^[-_A-Za-z-0-9][-_A-Za-z0-9 ]{1,126}[-_A-Za-z-0-9]$", self.image_name)
        if match is None:
            raise ImageBuilderActionError(
                "Image name '{0}' failed to satisfy constraint: ".format(self.image_name)
                + "Member must satisfy regular expression pattern: [-_A-Za-z-0-9][-_A-Za-z0-9 ]{1,126}[-_A-Za-z-0-9]"
            )
        if len(self.image_name) > 1024 - len(AMI_NAME_REQUIRED_SUBSTRING):
            raise ImageBuilderActionError(
                "Image name failed to satisfy constraint, the length should be shorter than {0}".format(
                    str(1024 - len(AMI_NAME_REQUIRED_SUBSTRING))
                )
            )
