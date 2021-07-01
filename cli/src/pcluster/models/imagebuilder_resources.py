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
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.aws_resources import StackInfo
from pcluster.aws.common import AWSClientError
from pcluster.constants import (
    PCLUSTER_IMAGE_BUILD_LOG_TAG,
    PCLUSTER_IMAGE_CONFIG_TAG,
    PCLUSTER_IMAGE_ID_TAG,
    PCLUSTER_S3_BUCKET_TAG,
    PCLUSTER_S3_IMAGE_DIR_TAG,
    PCLUSTER_VERSION_TAG,
)
from pcluster.models.common import BadRequest, LimitExceeded


class StackError(Exception):
    """Represent stack errors."""

    def __init__(self, message: str):
        super().__init__(message)


class NonExistingStackError(StackError):
    """Represent an error if stack doesn't exist."""

    def __init__(self, stack_name):
        super().__init__(f"ImageBuilder stack {stack_name} does not exist.")


class LimitExceededStackError(StackError, LimitExceeded):
    """Represent an error if we exceeded the limit of some downstream AWS service."""

    def __init__(self, message: str):
        super().__init__(message=message)


class BadRequestStackError(StackError, BadRequest):
    """Represent an error due to a problem in the request."""

    def __init__(self, message: str):
        super().__init__(message=message)


class ImageBuilderStack(StackInfo):
    """Class representing a running stack associated to a building image."""

    def __init__(self, stack_data: dict):
        """Init stack info."""
        super().__init__(stack_data)
        try:
            self._imagebuilder_image_resource = AWSApi.instance().cfn.describe_stack_resource(
                self.name, "ParallelClusterImage"
            )
        except AWSClientError:
            self._imagebuilder_image_resource = None

    @property
    def s3_artifact_directory(self):
        """Return the artifact directory of the bucket used to store image information."""
        return self.get_tag(PCLUSTER_S3_IMAGE_DIR_TAG)

    @property
    def s3_bucket_name(self):
        """Return the name of the bucket used to store image information."""
        return self.get_tag(PCLUSTER_S3_BUCKET_TAG)

    @property
    def config_url(self) -> str:
        """Return config url in S3 bucket."""
        return self.get_tag(PCLUSTER_IMAGE_CONFIG_TAG)

    @property
    def pcluster_image_id(self):
        """Return image id tag value."""
        return self.get_tag(PCLUSTER_IMAGE_ID_TAG)

    @property
    def version(self):
        """Return the version of ParallelCluster used to create the stack."""
        return self.get_tag(PCLUSTER_VERSION_TAG)

    @property
    def build_log(self):
        """Return build log arn."""
        return self.get_tag(PCLUSTER_IMAGE_BUILD_LOG_TAG)

    @property
    def image(self):
        """Return created image by imagebuilder stack."""
        try:
            image_id = self.image_id
            if image_id:
                return AWSApi.instance().ec2.describe_image(image_id)
            return None
        except AWSClientError:
            return None

    @property
    def imagebuilder_image_is_building(self):
        """Return imagebuilder image resource is building or not."""
        try:
            imagebuilder_image_status = self._imagebuilder_image_resource["StackResourceDetail"]["ResourceStatus"]
            if imagebuilder_image_status == "CREATE_IN_PROGRESS":
                return True
            return False
        except (TypeError, KeyError):
            return False

    @property
    def image_id(self):
        """Return output image id."""
        if self._imagebuilder_image_resource:
            try:
                image_build_version_arn = self._imagebuilder_image_resource["StackResourceDetail"]["PhysicalResourceId"]
                return AWSApi.instance().imagebuilder.get_image_id(image_build_version_arn)
            except (AWSClientError, KeyError):
                return None
        return None

    @property
    def image_state(self):
        """Return the ImageBuilder image state."""
        if self._imagebuilder_image_resource:
            try:
                image_build_version_arn = self._imagebuilder_image_resource["StackResourceDetail"]["PhysicalResourceId"]
                return AWSApi.instance().imagebuilder.get_image_state(image_build_version_arn)
            except (AWSClientError, KeyError):
                return None
        return None
