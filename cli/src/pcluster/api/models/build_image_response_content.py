# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=R0801


from typing import List

from pcluster.api import util
from pcluster.api.models.base_model_ import Model
from pcluster.api.models.config_validation_message import ConfigValidationMessage
from pcluster.api.models.image_info_summary import ImageInfoSummary


class BuildImageResponseContent(Model):
    """NOTE: This class is auto generated by OpenAPI Generator (https://openapi-generator.tech).

    Do not edit the class manually.
    """

    def __init__(self, image=None, validation_messages=None):
        """BuildImageResponseContent - a model defined in OpenAPI

        :param image: The image of this BuildImageResponseContent.
        :type image: ImageInfoSummary
        :param validation_messages: The validation_messages of this BuildImageResponseContent.
        :type validation_messages: List[ConfigValidationMessage]
        """
        self.openapi_types = {"image": ImageInfoSummary, "validation_messages": List[ConfigValidationMessage]}

        self.attribute_map = {"image": "image", "validation_messages": "validationMessages"}

        self._image = image
        self._validation_messages = validation_messages

    @classmethod
    def from_dict(cls, dikt) -> "BuildImageResponseContent":
        """Returns the dict as a model

        :param dikt: A dict.
        :type: dict
        :return: The BuildImageResponseContent of this BuildImageResponseContent.
        :rtype: BuildImageResponseContent
        """
        return util.deserialize_model(dikt, cls)

    @property
    def image(self):
        """Gets the image of this BuildImageResponseContent.


        :return: The image of this BuildImageResponseContent.
        :rtype: ImageInfoSummary
        """
        return self._image

    @image.setter
    def image(self, image):
        """Sets the image of this BuildImageResponseContent.


        :param image: The image of this BuildImageResponseContent.
        :type image: ImageInfoSummary
        """
        if image is None:
            raise ValueError("Invalid value for `image`, must not be `None`")

        self._image = image

    @property
    def validation_messages(self):
        """Gets the validation_messages of this BuildImageResponseContent.

        List of messages collected during image config validation whose level is lower than the validationFailureLevel
        set by the user

        :return: The validation_messages of this BuildImageResponseContent.
        :rtype: List[ConfigValidationMessage]
        """
        return self._validation_messages

    @validation_messages.setter
    def validation_messages(self, validation_messages):
        """Sets the validation_messages of this BuildImageResponseContent.

        List of messages collected during image config validation whose level is lower than the validationFailureLevel
        set by the user

        :param validation_messages: The validation_messages of this BuildImageResponseContent.
        :type validation_messages: List[ConfigValidationMessage]
        """
        self._validation_messages = validation_messages
