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

import pkg_resources

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.aws_resources import ImageInfo
from pcluster.aws.common import (
    AWSClientError,
    BadRequestError,
    ImageNotFoundError,
    LimitExceededError,
    StackNotFoundError,
    get_region,
)
from pcluster.config.common import BaseTag
from pcluster.constants import (
    IMAGEBUILDER_RESOURCE_NAME_PREFIX,
    PCLUSTER_IMAGE_BUILD_LOG_TAG,
    PCLUSTER_IMAGE_CONFIG_TAG,
    PCLUSTER_IMAGE_ID_REGEX,
    PCLUSTER_IMAGE_ID_TAG,
    PCLUSTER_IMAGE_NAME_TAG,
    PCLUSTER_S3_BUCKET_TAG,
    PCLUSTER_S3_IMAGE_DIR_TAG,
    PCLUSTER_VERSION_TAG,
)
from pcluster.models.imagebuilder_resources import (
    BadRequestStackError,
    ImageBuilderStack,
    LimitExceededStackError,
    NonExistingStackError,
    StackError,
)
from pcluster.models.s3_bucket import S3Bucket, S3BucketFactory
from pcluster.schemas.imagebuilder_schema import ImageBuilderSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import generate_random_name_with_prefix, get_installed_version, get_partition
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


class LimitExceededImageBuilderActionError(ImageBuilderActionError):
    """Represent an error during the execution of an action on the imagebuilder due to limit exceeded."""

    def __init__(self, message: str):
        super().__init__(message)


class BadRequestImageBuilderActionError(ImageBuilderActionError):
    """Represent an error during the execution of an action due to exceeding the limit of some AWS service."""

    def __init__(self, message: str, validation_failures: list = None):
        super().__init__(message, validation_failures)


class ConflictImageBuilderActionError(ImageBuilderActionError):
    """Represent an error due to another image/stack with the same name already existing."""

    def __init__(self, message: str):
        super().__init__(message)


class ImageError(Exception):
    """Represent image errors."""

    def __init__(self, message: str):
        super().__init__(message)


class LimitExceededImageError(ImageError):
    """Represent image errors due to limits exceeded."""

    def __init__(self, message: str):
        super().__init__(message)


class BadRequestImageError(ImageError):
    """Represent image errors due to a bad request."""

    def __init__(self, message: str):
        super().__init__(message)


class NonExistingImageError(ImageError):
    """Represent an error if image does not exist."""

    def __init__(self, image_id):
        super().__init__(f"Image {image_id} does not exist.")


def _stack_error_mapper(error, message):
    if isinstance(error, LimitExceededError):
        return LimitExceededStackError(message)
    elif isinstance(error, BadRequestError):
        return BadRequestStackError(message)
    else:
        return StackError(message)


def _image_error_mapper(error, message):
    if isinstance(error, LimitExceededError):
        return LimitExceededImageError(message)
    elif isinstance(error, BadRequestError):
        return BadRequestImageError(message)
    else:
        return ImageError(message)


def _imagebuilder_error_mapper(error, message):
    if isinstance(error, (LimitExceededImageError, LimitExceededStackError, LimitExceededError)):
        return LimitExceededImageBuilderActionError(message)
    elif isinstance(error, (BadRequestImageError, BadRequestStackError, BadRequestError)):
        return BadRequestImageBuilderActionError(message)
    else:
        return ImageBuilderActionError(message)


class ImageBuilder:
    """Represent a building image, composed by an ImageBuilder config and an ImageBuilderStack."""

    def __init__(
        self, image: ImageInfo = None, image_id: str = None, config: dict = None, stack: ImageBuilderStack = None
    ):
        self.image_id = image_id
        self.__source_config = config
        self.__stack = stack
        self.__image = image
        self.__config_url = None
        self.__config = None
        self.__bucket = None
        self.template_body = None
        self._s3_artifacts_dict = {
            "root_directory": "parallelcluster",
            "root_image_directory": "images",
            "config_name": "image-config.yaml",
            "template_name": "aws-parallelcluster-imagebuilder.cfn.yaml",
            "custom_artifacts_name": "artifacts.zip",
        }
        self.__s3_artifact_dir = None

    @property
    def s3_artifact_dir(self):
        """Get s3 artifacts dir."""
        if self.__s3_artifact_dir is None:
            self.__s3_artifact_dir = self._get_artifact_dir()
        return self.__s3_artifact_dir

    @property
    def config_url(self):
        """Return configuration file S3 bucket url."""
        if not self.__config_url:
            # get config url in build image command
            if self.__source_config:
                self.__config_url = self.bucket.get_config_s3_url(self._s3_artifacts_dict.get("config_name"))
            else:
                if self.__image:
                    self.__config_url = self.image.config_url
                elif self.__stack:
                    self.__config_url = self.stack.config_url
                else:
                    ImageBuilderActionError(f"Unable to get image {self.image_id} config url.")
        return self.__config_url

    @property
    def stack(self):
        """Return the ImageBuilderStack object."""
        if not self.__stack:
            try:
                self.__stack = ImageBuilderStack(AWSApi.instance().cfn.describe_stack(self.image_id))
            except StackNotFoundError:
                raise NonExistingStackError(self.image_id)
            except AWSClientError as e:
                raise _stack_error_mapper(e, f"Unable to get image {self.image_id}, due to {e}")
        return self.__stack

    @property
    def image(self):
        """Return Image object."""
        if not self.__image:
            try:
                self.__image = AWSApi.instance().ec2.describe_image_by_id_tag(self.image_id)
            except ImageNotFoundError:
                raise NonExistingImageError(self.image_id)
            except AWSClientError as e:
                raise _image_error_mapper(e, f"Unable to get image {self.image_id}, due to {e}.")

        return self.__image

    @property
    def imagebuild_status(self):
        """Return the status of the stack of build image process."""
        try:
            cfn_status = self.stack.status
            for key, value in ImageBuilderStatusMapping.items():
                if cfn_status in value:
                    return key
            return None
        except StackError as e:
            raise _imagebuilder_error_mapper(e, f"Unable to get image {self.image_id} status , due to {e}")

    @property
    def source_config(self):
        """Return source config, only called by build image process."""
        return self.__source_config

    @property
    def config(self):
        """Return ImageBuilder Config object, only called by build image process."""
        if not self.__config and self.__source_config:
            self.__config = ImageBuilderSchema().load(self.__source_config)
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
            service_name=self.image_id,
            stack_name=self.image_id,
            custom_s3_bucket=custom_bucket_name,
            artifact_directory=self.s3_artifact_dir,
        )
        return self.__bucket

    def _get_custom_bucket(self):
        """Try to get custom bucket name from image tag or stack tag."""
        custom_bucket_name = None
        try:
            custom_bucket_name = self.image.s3_bucket_name
        except ImageError as e:
            if not isinstance(e, NonExistingImageError):
                raise _imagebuilder_error_mapper(e, f"Unable to get S3 bucket name from image {self.image_id} . {e}")

        if custom_bucket_name is None:
            try:
                custom_bucket_name = self.stack.s3_bucket_name
            except StackError as e:
                raise _imagebuilder_error_mapper(e, f"Unable to get S3 bucket name from image {self.image_id}. {e}")

        return (
            custom_bucket_name
            if custom_bucket_name != S3Bucket.get_bucket_name(AWSApi.instance().sts.get_account_id(), get_region())
            else None
        )

    def _get_artifact_dir(self):
        """Get artifact directory from image tag or stack tag."""
        s3_artifact_dir = None
        try:
            s3_artifact_dir = self.image.s3_artifact_directory
        except ImageError as e:
            if not isinstance(e, NonExistingImageError):
                LOGGER.error("Unable to find tag %s in image %s.", PCLUSTER_S3_IMAGE_DIR_TAG, self.image_id)
                raise _imagebuilder_error_mapper(e, f"Unable to get artifact directory from image {self.image_id}. {e}")

        if s3_artifact_dir is None:
            try:
                s3_artifact_dir = self.stack.s3_artifact_directory

                if s3_artifact_dir is None:
                    raise ImageBuilderActionError(
                        "No artifact directory found in image tag and cloudformation stack tag."
                    )
            except StackError as e:
                raise _imagebuilder_error_mapper(e, f"Unable to get artifact directory from image {self.image_id}. {e}")

        return s3_artifact_dir

    def _generate_artifact_dir(self):
        """
        Generate artifact directory in S3 bucket.

        Image artifact dir is generated before cfn stack creation and only generate once.
        artifact_directory: e.g. parallelcluster/{version}/images/{image_id}-jfr4odbeonwb1w5k
        """
        service_directory = generate_random_name_with_prefix(self.image_id)
        self.__s3_artifact_dir = "/".join(
            [
                self._s3_artifacts_dict.get("root_directory"),
                get_installed_version(),
                self._s3_artifacts_dict.get("root_image_directory"),
                service_directory,
            ]
        )

    def validate_create_request(self, suppress_validators, validation_failure_level):
        """Validate a create request.

        :param suppress_validators: the validators we want to suppress when checking the configuration
        :param validation_failure_level: the level above which we throw an exception when validating the configuration
        """
        self._validate_id()
        self._validate_no_existing_image()
        self._validate_config(suppress_validators, validation_failure_level)

    def _validate_config(self, suppress_validators, validation_failure_level):
        """Validate the configuration, throwing an exception for failures above a given failure level."""
        if not suppress_validators:
            validation_failures = self.config.validate()
            for failure in validation_failures:
                if failure.level.value >= FailureLevel(validation_failure_level).value:
                    raise BadRequestImageBuilderActionError(
                        message="Configuration is invalid", validation_failures=validation_failures
                    )

    def _validate_no_existing_image(self):
        """Validate that no existing image or stack with the same ImageBuilder image_id exists."""
        if AWSApi.instance().ec2.image_exists(self.image_id):
            raise ConflictImageBuilderActionError(f"ParallelCluster image {self.image_id} already exists.")

        if AWSApi.instance().cfn.stack_exists(self.image_id):
            raise ConflictImageBuilderActionError(
                f"ParallelCluster build infrastructure for image {self.image_id} already exists"
            )

    def create(
        self,
        disable_rollback: bool = True,
        suppress_validators: bool = False,
        validation_failure_level: FailureLevel = FailureLevel.ERROR,
    ):
        """Create the CFN Stack and associate resources."""
        self.validate_create_request(suppress_validators, validation_failure_level)

        # Generate artifact directory for image
        self._generate_artifact_dir()

        creation_result = None
        artifacts_uploaded = False
        try:
            self._upload_config()

            LOGGER.info("Building ParallelCluster image: %s", self.image_id)

            # Generate cdk cfn template
            self.template_body = CDKTemplateBuilder().build_imagebuilder_template(
                image_config=self.config, image_id=self.image_id, bucket=self.bucket
            )

            # upload generated template
            self._upload_artifacts()
            artifacts_uploaded = True

            # Stack creation
            creation_result = AWSApi.instance().cfn.create_stack_from_url(
                stack_name=self.image_id,
                template_url=self.bucket.get_cfn_template_url(
                    template_name=self._s3_artifacts_dict.get("template_name")
                ),
                disable_rollback=disable_rollback,
                tags=self._get_cfn_tags(),
                capabilities="CAPABILITY_NAMED_IAM",
            )

            self.__stack = ImageBuilderStack(AWSApi.instance().cfn.describe_stack(self.image_id))

            LOGGER.debug("StackId: %s", self.stack.id)
            LOGGER.info("Status: %s", self.stack.status)

        except Exception as e:
            LOGGER.critical(e)
            if not creation_result and artifacts_uploaded:
                # Cleanup S3 artifacts if stack is not created yet
                self.bucket.delete_s3_artifacts()
            raise _imagebuilder_error_mapper(e, f"ParallelCluster image build infrastructure creation failed.\n{e}")

    def _upload_config(self):
        """Upload source config to S3 bucket."""
        try:
            if self.config:
                # Upload original config
                self.bucket.upload_config(
                    config=self.source_config, config_name=self._s3_artifacts_dict.get("config_name")
                )

        except Exception as e:
            raise _imagebuilder_error_mapper(
                e,
                f"Unable to upload imagebuilder config to the S3 bucket {self.bucket.name} due to exception: {e}",
            )

    def _upload_artifacts(self):
        """
        Upload image specific resources and image template.

        All dirs contained in resource dir will be uploaded as zip files to
        /{version}/parallelcluster/{version}/images/{image_id}-jfr4odbeonwb1w5k/{resource_dir}/artifacts.zip.
        All files contained in root dir will be uploaded to
        /{version}/parallelcluster/{version}/images/{image_id}-jfr4odbeonwb1w5k/{resource_dir}/artifact.
        """
        try:
            if self.template_body:
                # upload cfn template
                self.bucket.upload_cfn_template(self.template_body, self._s3_artifacts_dict.get("template_name"))

            resources = pkg_resources.resource_filename(__name__, "../resources/custom_resources")
            self.bucket.upload_resources(
                resource_dir=resources, custom_artifacts_name=self._s3_artifacts_dict.get("custom_artifacts_name")
            )
        except Exception as e:
            raise _imagebuilder_error_mapper(
                e,
                f"Unable to upload imagebuilder cfn template to the S3 bucket {self.bucket.name} due to exception: {e}",
            )

    def delete(self, force=False):  # noqa: C901
        """Delete CFN Stack and associate resources and deregister the image."""
        if force or (not self._check_instance_using_image() and not self._check_image_is_shared()):
            try:
                if AWSApi.instance().cfn.stack_exists(self.image_id):
                    if self.stack.imagebuilder_image_is_building:
                        raise ImageBuilderActionError(
                            "Image cannot be deleted because EC2 ImageBuilder Image has a running workflow."
                        )
                    # Delete stack
                    AWSApi.instance().cfn.delete_stack(self.image_id)

                if AWSApi.instance().ec2.image_exists(image_id=self.image_id, build_status_avaliable=False):
                    # Deregister image
                    AWSApi.instance().ec2.deregister_image(self.image.id)

                    # Delete snapshot
                    for snapshot_id in self.image.snapshot_ids:
                        AWSApi.instance().ec2.delete_snapshot(snapshot_id)

                # Delete s3 image directory
                try:
                    self.bucket.check_bucket_exists()
                    self.bucket.delete_s3_artifacts()
                except AWSClientError:
                    logging.warning("S3 bucket %s does not exist, skip image s3 artifacts deletion.", self.bucket.name)

                # Delete log group
                try:
                    AWSApi.instance().logs.delete_log_group(self._log_group_name())
                except AWSClientError:
                    logging.warning("Unable to delete log group %s.", self._log_group_name())

            except (AWSClientError, ImageError) as e:
                raise _imagebuilder_error_mapper(e, f"Unable to delete image and stack, due to {str(e)}")

    def _check_image_is_shared(self):
        """Check the image is shared with other account."""
        try:
            result = AWSApi.instance().ec2.get_image_shared_account_ids(self.image.id)
            if result:
                logging.error(
                    "Image %s is shared with accounts or group %s. "
                    "In case you want to delete the image, please use the --force flag.",
                    self.image_id,
                    str(result),
                )
                raise ImageBuilderActionError("Unable to delete image and stack")
            return False
        except (AWSClientError, ImageError) as e:
            if isinstance(e, NonExistingImageError):
                return False
            raise _imagebuilder_error_mapper(e, f"Unable to delete image and stack, due to {str(e)}")

    def _check_instance_using_image(self):
        """Check image is used by other instances."""
        try:
            result = AWSApi.instance().ec2.get_instance_ids_by_ami_id(self.image.id)
            if result:
                logging.error(
                    "Image %s is used by instances %s. "
                    "In case you want to delete the image, please use the --force flag.",
                    self.image_id,
                    str(result),
                )
                raise BadRequestImageBuilderActionError(
                    "Unable to delete image and stack: image {} is used by instances {}.".format(
                        self.image_id, str(result)
                    )
                )
            return False
        except (AWSClientError, ImageError) as e:
            if isinstance(e, NonExistingImageError):
                return False
            raise _imagebuilder_error_mapper(e, f"Unable to delete image and stack, due to {str(e)}")

    def _validate_id(self):
        match = re.match(PCLUSTER_IMAGE_ID_REGEX, self.image_id)
        if match is None:
            raise BadRequestImageBuilderActionError(
                "Image id '{0}' failed to satisfy constraint: ".format(self.image_id)
                + "The process id can contain only alphanumeric characters (case-sensitive) and hyphens. "
                + "It must start with an alphabetic character and can't be longer than 128 characters."
            )

    def _get_cfn_tags(self):
        """Get cfn tags."""
        cfn_tags = copy.deepcopy(self.config.build.tags) or []
        self.__config_url = self.bucket.get_config_s3_url(self._s3_artifacts_dict.get("config_name"))
        tag_list = [
            {
                "key": PCLUSTER_IMAGE_NAME_TAG,
                "value": self.config.image.name if self.config.image and self.config.image.name else self.image_id,
            },
            {"key": PCLUSTER_VERSION_TAG, "value": get_installed_version()},
            {"key": PCLUSTER_IMAGE_ID_TAG, "value": self.image_id},
            {"key": PCLUSTER_S3_BUCKET_TAG, "value": self.bucket.name},
            {"key": PCLUSTER_S3_IMAGE_DIR_TAG, "value": self.s3_artifact_dir},
            {"key": PCLUSTER_IMAGE_BUILD_LOG_TAG, "value": self._get_log_group_arn()},
            {"key": PCLUSTER_IMAGE_CONFIG_TAG, "value": self.config_url},
        ]
        for tag in tag_list:
            cfn_tags.append(BaseTag(key=tag.get("key"), value=tag.get("value")))
        return [{"Key": tag.key, "Value": tag.value} for tag in cfn_tags]

    def _get_log_group_arn(self):
        """Get log group arn."""
        return "arn:{0}:logs:{1}:{2}:log-group:{3}".format(
            get_partition(), get_region(), AWSApi.instance().sts.get_account_id(), self._log_group_name()
        )

    def _log_group_name(self):
        """Get log group name."""
        image_recipe_name = "{0}-{1}".format(IMAGEBUILDER_RESOURCE_NAME_PREFIX, self.image_id)
        return "/aws/imagebuilder/{0}".format(image_recipe_name)
