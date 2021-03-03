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
import json
import logging
import re

from common.aws.aws_api import AWSApi
from common.aws.aws_resources import StackInfo
from common.boto3.common import AWSClientError
from common.imagebuilder_utils import AMI_NAME_REQUIRED_SUBSTRING
from pcluster.models.common import BaseTag
from pcluster.schemas.imagebuilder_schema import ImageBuilderSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import get_installed_version

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

    @property
    def get_source_config(self):
        """Get source config from metadata."""
        try:
            return AWSApi.instance().cfn.get_template(self.name).get("Metadata").get("Config")
        except (AWSClientError, KeyError):
            return None


class ImageBuilder:
    """Represent a building image, composed by an ImageBuilder config and an ImageBuilderStack."""

    def __init__(self, image_name: str, config: dict = None, stack: ImageBuilderStack = None):
        self.image_name = image_name
        self.__source_config = config
        self.__stack = stack
        self.__config = None
        self.template_body = None
        self.config_version = None

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
        """Return original config used to create the imagebuilder stack."""
        if not self.__source_config:
            self.__source_config = self.stack.get_source_config
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

    def create(self, disable_rollback: bool = False):
        """Create the CFN Stack and associate resources."""
        # validate image name
        self._validate_image_name()

        # check imagebuilder stack existence
        if AWSApi.instance().cfn.stack_exists(self.image_name):
            raise ImageBuilderActionError(f"ImageBuilder stack {self.image_name} already exists")

        validation_failures = self.config.validate()
        if validation_failures:
            # TODO skip validation errors
            raise ImageBuilderActionError("Configuration is invalid", validation_failures=validation_failures)

        # Add tags information to the stack
        tags = copy.deepcopy(self.config.build.tags) or []
        tags.append(BaseTag(key="pcluster_build_image", value=get_installed_version()))
        tags = [{"Key": tag.key, "Value": tag.value} for tag in tags]

        try:
            LOGGER.info("Creating stack named: %s", self.image_name)

            # Generate cdk cfn template
            self.template_body = CDKTemplateBuilder().build_imagebuilder_template(
                imagebuild=self.config, image_name=self.image_name
            )

            # Stack creation
            AWSApi.instance().cfn.create_stack(
                stack_name=self.image_name,
                template_body=json.dumps(self.template_body),
                disable_rollback=disable_rollback,
                tags=tags,
            )

            self.__stack = ImageBuilderStack(AWSApi().instance().cfn.describe_stack(self.image_name))
            LOGGER.debug("StackId: %s", self.stack.id)
            LOGGER.info("Status: %s", self.stack.status)

        except Exception as e:
            LOGGER.critical(e)
            raise ImageBuilderActionError(f"ImageBuilder stack creation failed.\n{e}")

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
