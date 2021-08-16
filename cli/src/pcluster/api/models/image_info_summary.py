# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=R0801


import re

from pcluster.api import util
from pcluster.api.models.base_model_ import Model
from pcluster.api.models.cloud_formation_stack_status import CloudFormationStackStatus
from pcluster.api.models.image_build_status import ImageBuildStatus


class ImageInfoSummary(Model):
    """NOTE: This class is auto generated by OpenAPI Generator (https://openapi-generator.tech).

    Do not edit the class manually.
    """

    def __init__(
        self,
        image_id=None,
        image_build_status=None,
        ec2_image_id=None,
        cloudformation_stack_status=None,
        cloudformation_stack_arn=None,
        region=None,
        version=None,
    ):
        """ImageInfoSummary - a model defined in OpenAPI

        :param image_id: The image_id of this ImageInfoSummary.
        :type image_id: str
        :param image_build_status: The image_build_status of this ImageInfoSummary.
        :type image_build_status: ImageBuildStatus
        :param cloudformation_stack_status: The cloudformation_stack_status of this ImageInfoSummary.
        :type cloudformation_stack_status: CloudFormationStackStatus
        :param cloudformation_stack_arn: The cloudformation_stack_arn of this ImageInfoSummary.
        :type cloudformation_stack_arn: str
        :param ec2_image_id: The ec2_image_id of this ImageInfoSummary.
        :type ec2_image_id: str
        :param region: The region of this ImageInfoSummary.
        :type region: str
        :param version: The version of this ImageInfoSummary.
        :type version: str
        """
        self.openapi_types = {
            "image_id": str,
            "image_build_status": ImageBuildStatus,
            "cloudformation_stack_status": CloudFormationStackStatus,
            "cloudformation_stack_arn": str,
            "ec2_image_id": str,
            "region": str,
            "version": str,
        }

        self.attribute_map = {
            "image_id": "imageId",
            "image_build_status": "imageBuildStatus",
            "cloudformation_stack_status": "cloudformationStackStatus",
            "cloudformation_stack_arn": "cloudformationStackArn",
            "ec2_image_id": "ec2ImageId",
            "region": "region",
            "version": "version",
        }

        self._image_id = image_id
        self._image_build_status = image_build_status
        self._cloudformation_stack_status = cloudformation_stack_status
        self._cloudformation_stack_arn = cloudformation_stack_arn
        self._ec2_image_id = ec2_image_id
        self._region = region
        self._version = version

    @classmethod
    def from_dict(cls, dikt) -> "ImageInfoSummary":
        """Returns the dict as a model

        :param dikt: A dict.
        :type: dict
        :return: The ImageInfoSummary of this ImageInfoSummary.
        :rtype: ImageInfoSummary
        """
        return util.deserialize_model(dikt, cls)

    @property
    def image_id(self):
        """Gets the image_id of this ImageInfoSummary.

        Id of the image.

        :return: The image_id of this ImageInfoSummary.
        :rtype: str
        """
        return self._image_id

    @image_id.setter
    def image_id(self, image_id):
        """Sets the image_id of this ImageInfoSummary.

        Id of the image.

        :param image_id: The image_id of this ImageInfoSummary.
        :type image_id: str
        """
        if image_id is None:
            raise ValueError("Invalid value for `image_id`, must not be `None`")
        if image_id is not None and not re.search(r"^[a-zA-Z][a-zA-Z0-9-]+$", image_id):
            raise ValueError(
                "Invalid value for `image_id`, must be a follow pattern or equal to `/^[a-zA-Z][a-zA-Z0-9-]+$/`"
            )

        self._image_id = image_id

    @property
    def image_build_status(self):
        """Gets the image_build_status of this ImageInfoSummary.


        :return: The image_build_status of this ImageInfoSummary.
        :rtype: ImageBuildStatus
        """
        return self._image_build_status

    @image_build_status.setter
    def image_build_status(self, image_build_status):
        """Sets the image_build_status of this ImageInfoSummary.


        :param image_build_status: The image_build_status of this ImageInfoSummary.
        :type image_build_status: ImageBuildStatus
        """
        if image_build_status is None:
            raise ValueError("Invalid value for `image_build_status`, must not be `None`")

        self._image_build_status = image_build_status

    @property
    def cloudformation_stack_status(self):
        """Gets the cloudformation_stack_status of this ImageInfoSummary.


        :return: The cloudformation_stack_status of this ImageInfoSummary.
        :rtype: CloudFormationStackStatus
        """
        return self._cloudformation_stack_status

    @cloudformation_stack_status.setter
    def cloudformation_stack_status(self, cloudformation_stack_status):
        """Sets the cloudformation_stack_status of this ImageInfoSummary.


        :param cloudformation_stack_status: The cloudformation_stack_status of this ImageInfoSummary.
        :type cloudformation_stack_status: CloudFormationStackStatus
        """
        self._cloudformation_stack_status = cloudformation_stack_status

    @property
    def cloudformation_stack_arn(self):
        """Gets the cloudformation_stack_arn of this ImageInfoSummary.

        ARN of the main CloudFormation stack.

        :return: The cloudformation_stack_arn of this ImageInfoSummary.
        :rtype: str
        """
        return self._cloudformation_stack_arn

    @cloudformation_stack_arn.setter
    def cloudformation_stack_arn(self, cloudformation_stack_arn):
        """Sets the cloudformation_stack_arn of this ImageInfoSummary.

        ARN of the main CloudFormation stack.

        :param cloudformation_stack_arn: The cloudformation_stack_arn of this ImageInfoSummary.
        :type cloudformation_stack_arn: str
        """
        self._cloudformation_stack_arn = cloudformation_stack_arn

    @property
    def ec2_image_id(self):
        """Gets the ec2_image_id of this ImageInfoSummary.

        Ec2 Id of the imag.

        :return: The ec2_image_id of this ImageInfoSummary.
        :rtype: str
        """
        return self._ec2_image_id

    @ec2_image_id.setter
    def ec2_image_id(self, ec2_image_id):
        """Sets the ec2_image_id of this ImageInfoSummary.

        Ec2 Id of the image.

        :param ec2_image_id: The ec2_image_id of this ImageInfoSummary.
        :type ec2_image_id: str
        """
        if ec2_image_id is None:
            raise ValueError("Invalid value for `ec2_image_id`, must not be `None`")

        self._ec2_image_id = ec2_image_id

    @property
    def region(self):
        """Gets the region of this ImageInfoSummary.

        AWS region where the image is built.

        :return: The region of this ImageInfoSummary.
        :rtype: str
        """
        return self._region

    @region.setter
    def region(self, region):
        """Sets the region of this ImageInfoSummary.

        AWS region where the image is built.

        :param region: The region of this ImageInfoSummary.
        :type region: str
        """
        if region is None:
            raise ValueError("Invalid value for `region`, must not be `None`")

        self._region = region

    @property
    def version(self):
        """Gets the version of this ImageInfoSummary.

        ParallelCluster version used to build the image.

        :return: The version of this ImageInfoSummary.
        :rtype: str
        """
        return self._version

    @version.setter
    def version(self, version):
        """Sets the version of this ImageInfoSummary.

        ParallelCluster version used to build the image.

        :param version: The version of this ImageInfoSummary.
        :type version: str
        """
        if version is None:
            raise ValueError("Invalid value for `version`, must not be `None`")

        self._version = version
