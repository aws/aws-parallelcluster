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
import gzip
import logging
import os
import re
from typing import Set
import tarfile
import tempfile
import time
from datetime import datetime

import pkg_resources
from dateutil.parser import parse

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
from pcluster.config.common import BaseTag, ValidatorSuppressor
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
    STACK_EVENTS_LOG_STREAM_NAME,
)
from pcluster.models.common import BadRequest, Conflict, LimitExceeded, parse_config
from pcluster.models.cluster_resources import FiltersParserError
from pcluster.models.common_resources import LogGroupTimeFiltersParser
from pcluster.models.imagebuilder_resources import (
    BadRequestStackError,
    ImageBuilderStack,
    LimitExceededStackError,
    NonExistingStackError,
    StackError,
)
from pcluster.models.s3_bucket import S3Bucket, S3BucketFactory, S3FileFormat
from pcluster.schemas.imagebuilder_schema import ImageBuilderSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import generate_random_name_with_prefix, get_installed_version, get_partition, isoformat_to_epoch
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


class LimitExceededImageBuilderActionError(ImageBuilderActionError, LimitExceeded):
    """Represent an error during the execution of an action due to exceeding the limit of some AWS service."""

    def __init__(self, message: str):
        super().__init__(message)


class BadRequestImageBuilderActionError(ImageBuilderActionError, BadRequest):
    """Represent an error during the execution of an action due to a problem with the request."""

    def __init__(self, message: str, validation_failures: list = None):
        super().__init__(message, validation_failures)


class ConflictImageBuilderActionError(ImageBuilderActionError, Conflict):
    """Represent an error due to another image/stack with the same name already existing."""

    def __init__(self, message: str):
        super().__init__(message)


class ImageError(Exception):
    """Represent image errors."""

    def __init__(self, message: str):
        super().__init__(message)


class LimitExceededImageError(ImageError, LimitExceeded):
    """Represent image errors due to limits exceeded."""

    def __init__(self, message: str):
        super().__init__(message)


class BadRequestImageError(ImageError, BadRequest):
    """Represent image errors due to a bad request."""

    def __init__(self, message: str):
        super().__init__(message)


class NonExistingImageError(ImageError):
    """Represent an error if image does not exist."""

    def __init__(self, image_id):
        super().__init__(f"Image {image_id} does not exist.")


def _stack_error_mapper(error, message):
    if isinstance(error, (LimitExceeded, LimitExceededError)):
        return LimitExceededStackError(message)
    elif isinstance(error, (BadRequest, BadRequestError)):
        return BadRequestStackError(message)
    else:
        return StackError(message)


def _image_error_mapper(error, message):
    if isinstance(error, (LimitExceeded, LimitExceededError)):
        return LimitExceededImageError(message)
    elif isinstance(error, (BadRequest, BadRequestError)):
        return BadRequestImageError(message)
    else:
        return ImageError(message)


def _imagebuilder_error_mapper(error, message=None):
    if message is None:
        message = str(error)

    if isinstance(error, (LimitExceeded, LimitExceededError)):
        return LimitExceededImageBuilderActionError(message)
    elif isinstance(error, (BadRequest, BadRequestError)):
        return BadRequestImageBuilderActionError(message)
    elif isinstance(error, Conflict):
        return ConflictImageBuilderActionError(message)
    else:
        return ImageBuilderActionError(message)


class ImageBuilder:
    """Represent a building image, composed by an ImageBuilder config and an ImageBuilderStack."""

    def __init__(
        self, image: ImageInfo = None, image_id: str = None, config: str = None, stack: ImageBuilderStack = None
    ):
        self.image_id = image_id
        self.__source_config_text = config
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
            if self.__source_config_text:
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
                raise _stack_error_mapper(e, f"Unable to get image {self.image_id}, due to {e}.")
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
    def source_config_text(self):
        """Return source config, only called by build image process."""
        return self.__source_config_text

    @property
    def config(self):
        """Return ImageBuilder Config object, only called by build image process."""
        if not self.__config and self.__source_config_text:
            self.__config = ImageBuilderSchema().load(parse_config(self.__source_config_text))
        return self.__config

    @property
    def bucket(self):
        """Return a bucket configuration."""
        if self.__bucket:
            return self.__bucket

        if self.__source_config_text:
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

    def validate_create_request(self, validator_suppressors, validation_failure_level):
        """Validate a create request.

        :param validator_suppressors: the validators we want to suppress when checking the configuration
        :param validation_failure_level: the level above which we throw an exception when validating the configuration
        :return: the list of suppressed validation failures
        """
        self._validate_id()
        self._validate_no_existing_image()
        return self._validate_config(validator_suppressors, validation_failure_level)

    def _validate_config(self, validator_suppressors, validation_failure_level):
        """Validate the configuration, throwing an exception for failures above a given failure level."""
        validation_failures = self.config.validate(validator_suppressors)
        for failure in validation_failures:
            if failure.level.value >= FailureLevel(validation_failure_level).value:
                raise BadRequestImageBuilderActionError(
                    message="Configuration is invalid", validation_failures=validation_failures
                )
        return validation_failures

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
        validator_suppressors: Set[ValidatorSuppressor] = None,
        validation_failure_level: FailureLevel = FailureLevel.ERROR,
    ):
        """Create the CFN Stack and associate resources."""
        suppressed_validation_failures = self.validate_create_request(validator_suppressors, validation_failure_level)

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

            return suppressed_validation_failures

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
                    config=self.source_config_text,
                    config_name=self._s3_artifacts_dict.get("config_name"),
                    format=S3FileFormat.TEXT,
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
                    AWSApi.instance().logs.delete_log_group(self._log_group_name)
                except AWSClientError:
                    logging.warning("Unable to delete log group %s.", self._log_group_name)

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
            {"key": PCLUSTER_IMAGE_BUILD_LOG_TAG, "value": self._get_log_group_arn},
            {"key": PCLUSTER_IMAGE_CONFIG_TAG, "value": self.config_url},
        ]
        for tag in tag_list:
            cfn_tags.append(BaseTag(key=tag.get("key"), value=tag.get("value")))
        return [{"Key": tag.key, "Value": tag.value} for tag in cfn_tags]

    @property
    def _get_log_group_arn(self):
        """Get log group arn."""
        return "arn:{0}:logs:{1}:{2}:log-group:{3}".format(
            get_partition(), get_region(), AWSApi.instance().sts.get_account_id(), self._log_group_name
        )

    @property
    def _log_group_name(self):
        """Get log group name."""
        return f"/aws/imagebuilder/{IMAGEBUILDER_RESOURCE_NAME_PREFIX}-{self.image_id}"

    def export_logs(
        self,
        output: str,
        bucket: str,
        bucket_prefix: str = None,
        keep_s3_objects: bool = False,
        start_time: str = None,
        end_time: str = None,
    ):
        """
        Export image builder's logs in the given output path, by using given bucket as a temporary folder.

        :param output: file path to save log file archive to
        :param bucket: Temporary S3 bucket to be used to export cluster logs data
        :param bucket_prefix: Key path under which exported logs data will be stored in s3 bucket,
               also serves as top-level directory in resulting archive
        :param keep_s3_objects: Keep the exported objects exports to S3. The default behavior is to delete them
        :param start_time: Start time of interval of interest for log events. ISO 8601 format: YYYY-MM-DDThh:mm:ssTZD
        :param end_time: End time of interval of interest for log events. ISO 8601 format: YYYY-MM-DDThh:mm:ssTZD
        """
        # check stack
        stack_exists = self._stack_exists()
        if not stack_exists:
            LOGGER.debug("CloudFormation Stack for Image %s does not exist.", self.image_id)

        try:
            with tempfile.TemporaryDirectory() as logs_archive_tempdir:

                log_streams_dir = None
                if AWSApi.instance().logs.log_group_exists(self._log_group_name):
                    # check bucket
                    bucket_region = AWSApi.instance().s3.get_bucket_region(bucket_name=bucket)
                    if bucket_region != get_region():
                        raise ImageBuilderActionError(
                            "The bucket used for exporting logs must be in the same region as the image builder. "
                            f"The given image builder is in {get_region()}, "
                            f"but the given bucket's region is {bucket_region}."
                        )

                    # If the default bucket prefix is being used and there's nothing underneath that prefix already
                    # then we can delete everything under that prefix after downloading the data
                    # (unless keep-s3-objects is specified)
                    delete_everything_under_prefix = False
                    if not bucket_prefix:
                        bucket_prefix = f"{self.image_id}-logs-{datetime.now().timestamp()}"
                        delete_everything_under_prefix = AWSApi.instance().s3_resource.is_empty(bucket, bucket_prefix)

                    # Start export task
                    export_logs_filters = self._init_export_logs_filters(start_time, end_time)
                    task_id = self._export_logs_to_s3(
                        bucket=bucket,
                        bucket_prefix=bucket_prefix,
                        start_time=export_logs_filters.start_time,
                        end_time=export_logs_filters.end_time,
                    )

                    # Download exported S3 objects to tempdir
                    try:
                        log_streams_dir = os.path.join(logs_archive_tempdir, bucket_prefix)
                        self._download_s3_objects_with_prefix(bucket, bucket_prefix, task_id, log_streams_dir)
                        LOGGER.debug("Archive of CloudWatch logs from image %s saved to %s", self.image_id, output)
                    except OSError:
                        raise ImageBuilderActionError(
                            "Unable to download archive logs from S3, double check your filters are correct."
                        )
                    finally:
                        if not keep_s3_objects:
                            if delete_everything_under_prefix:
                                delete_key = bucket_prefix
                            else:
                                delete_key = "/".join((bucket_prefix, task_id))
                            LOGGER.debug("Cleaning up S3 bucket %s. Deleting all objects under %s", bucket, delete_key)
                            AWSApi.instance().s3_resource.delete_objects(bucket_name=bucket, prefix=delete_key)

                stack_events_file = None
                if stack_exists:
                    # Get stack events and write them into a file
                    stack_events_file = os.path.join(logs_archive_tempdir, STACK_EVENTS_LOG_STREAM_NAME)
                    self._download_stack_events_file(stack_events_file)

                self._create_logs_archive(stack_events_file, log_streams_dir, output, bucket_prefix)
        except AWSClientError as e:
            raise ImageBuilderActionError(f"Unexpected error when exporting image's logs: {e}")

    def _stack_exists(self):
        stack_exists = True
        try:
            _ = self.stack
        except NonExistingStackError:
            stack_exists = False
        return stack_exists

    @staticmethod
    def _create_logs_archive(stack_events_file, log_streams_dir, output, log_streams_dir_archive_name):
        LOGGER.debug("Creating archive of logs and saving it to %s", output)
        with tarfile.open(output, "w:gz") as tar:
            if stack_events_file:
                tar.add(stack_events_file, arcname=STACK_EVENTS_LOG_STREAM_NAME)
            if log_streams_dir:
                tar.add(log_streams_dir, arcname=log_streams_dir_archive_name)

    def _download_stack_events_file(self, stack_events_file):
        """Save CFN stack events into a file."""
        stack_events = AWSApi.instance().cfn.get_stack_events(self.stack.name)
        with open(stack_events_file, "w") as cfn_events_file:
            for event in stack_events:
                cfn_events_file.write("%s\n" % AWSApi.instance().cfn.format_event(event))

    def _init_export_logs_filters(self, start_time, end_time):
        try:
            export_logs_filters = LogGroupTimeFiltersParser(
                log_group_name=self._log_group_name, start_time=start_time, end_time=end_time
            )
            export_logs_filters.validate()
        except FiltersParserError as e:
            raise ImageBuilderActionError(str(e))
        return export_logs_filters

    def _export_logs_to_s3(self, bucket, bucket_prefix=None, start_time=None, end_time=None):
        """Export the contents of a image's CloudWatch log group to an s3 bucket."""
        try:
            LOGGER.info("Starting export of logs from log group %s to s3 bucket %s", self._log_group_name, bucket)
            task_id = AWSApi.instance().logs.create_export_task(
                log_group_name=self._log_group_name,
                bucket=bucket,
                bucket_prefix=bucket_prefix,
                start_time=start_time,
                end_time=end_time,
            )

            result_status = self._wait_for_task_completion(task_id)
            if result_status != "COMPLETED":
                raise ImageBuilderActionError(
                    f"CloudWatch logs export task {task_id} failed with status: {result_status}"
                )
            return task_id
        except AWSClientError as e:
            # TODO use log type/class
            if "Please check if CloudWatch Logs has been granted permission to perform this operation." in str(e):
                raise ImageBuilderActionError(
                    f"CloudWatch Logs needs GetBucketAcl and PutObject permission for the s3 bucket {bucket}. "
                    "See https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/S3ExportTasks.html#S3Permissions "
                    "for more details."
                )
            raise ImageBuilderActionError(f"Unexpected error when starting export task: {e}")

    @staticmethod
    def _wait_for_task_completion(task_id):
        """Wait for the CloudWatch logs export task given by task_id to finish."""
        LOGGER.info("Waiting for export task with task ID=%s to finish...", task_id)
        status = "PENDING"
        still_running_statuses = ("PENDING", "PENDING_CANCEL", "RUNNING")
        while status in still_running_statuses:
            time.sleep(1)
            status = AWSApi.instance().logs.get_export_task_status(task_id)
        return status

    @staticmethod
    def _download_s3_objects_with_prefix(bucket_name, bucket_prefix, task_id, destdir):
        """Download all object in bucket with given prefix into destdir."""
        prefix = f"{bucket_prefix}/{task_id}"
        LOGGER.debug("Downloading exported logs from s3 bucket %s (under key %s) to %s", bucket_name, prefix, destdir)
        for archive_object in AWSApi.instance().s3_resource.get_objects(bucket_name=bucket_name, prefix=prefix):
            decompressed_path = os.path.dirname(os.path.join(destdir, archive_object.key))
            decompressed_path = decompressed_path.replace(
                r"{unwanted_path_segment}{sep}".format(unwanted_path_segment=prefix, sep=os.path.sep), ""
            )
            compressed_path = f"{decompressed_path}.gz"

            LOGGER.debug("Downloading object with key=%s to %s", archive_object.key, compressed_path)
            os.makedirs(os.path.dirname(compressed_path), exist_ok=True)
            AWSApi.instance().s3_resource.download_file(
                bucket_name=bucket_name, key=archive_object.key, output=compressed_path
            )

            # Create a decompressed copy of the downloaded archive and remove the original
            LOGGER.debug("Extracting object at %s to %s", compressed_path, decompressed_path)
            with gzip.open(compressed_path) as gfile, open(decompressed_path, "wb") as outfile:
                outfile.write(gfile.read())
            os.remove(compressed_path)

    def list_logs(self, next_token: str = None):
        """
        List image builder's logs.

        :param next_token: Token for paginated requests.
        :returns a dict with the structure {"logStreams": [], "stackEventsStream": {}}
        """
        try:
            # check stack
            stack_exists = self._stack_exists()
            if not stack_exists:
                LOGGER.debug("CloudFormation Stack for Image %s does not exist.", self.image_id)

            response = {}
            try:
                LOGGER.debug("Listing log streams from log group %s", self._log_group_name)
                response = AWSApi.instance().logs.describe_log_streams(
                    log_group_name=self._log_group_name, next_token=next_token
                )
            except AWSClientError:
                LOGGER.debug("Log Group %s doesn't exist.", self._log_group_name)

            if not next_token and stack_exists:
                # add CFN Stack information only at the first request, when next-token is not specified
                response["stackEventsStream"] = [
                    {
                        "Stack Events Stream": STACK_EVENTS_LOG_STREAM_NAME,
                        "Stack Creation Time": parse(self.stack.creation_time).isoformat(timespec="seconds"),
                    }
                ]
            return response

        except AWSClientError as e:
            raise ImageBuilderActionError(f"Unexpected error when retrieving cluster's logs: {e}")

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
        stack_exists = self._stack_exists()
        if not stack_exists:
            message = f"CloudFormation Stack for Image {self.image_id} does not exist."
            if log_stream_name == STACK_EVENTS_LOG_STREAM_NAME:
                raise ImageBuilderActionError(message)
            else:
                LOGGER.debug(message)

        try:
            if log_stream_name != STACK_EVENTS_LOG_STREAM_NAME:
                return AWSApi.instance().logs.get_log_events(
                    log_group_name=self._log_group_name,
                    log_stream_name=log_stream_name,
                    end_time=isoformat_to_epoch(end_time) if end_time else None,
                    start_time=isoformat_to_epoch(start_time) if start_time else None,
                    limit=limit,
                    start_from_head=start_from_head,
                    next_token=next_token,
                )
            else:
                stack_events = AWSApi.instance().cfn.get_stack_events(self.stack.name)
                stack_events.reverse()
                if limit:
                    if start_from_head:
                        stack_events = stack_events[:limit]
                    else:
                        stack_events = stack_events[len(stack_events) - limit :]  # noqa E203
                return {"events": stack_events}
        except AWSClientError as e:
            raise ImageBuilderActionError(f"Unexpected error when retrieving log events: {e}")
