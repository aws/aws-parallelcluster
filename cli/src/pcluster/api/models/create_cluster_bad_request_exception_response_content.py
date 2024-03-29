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


class CreateClusterBadRequestExceptionResponseContent(Model):
    """NOTE: This class is auto generated by OpenAPI Generator (https://openapi-generator.tech).

    Do not edit the class manually.
    """

    def __init__(self, configuration_validation_errors=None, message=None):
        """CreateClusterBadRequestExceptionResponseContent - a model defined in OpenAPI

        :param configuration_validation_errors: The configuration_validation_errors of this
        CreateClusterBadRequestExceptionResponseContent.
        :type configuration_validation_errors: List[ConfigValidationMessage]
        :param message: The message of this CreateClusterBadRequestExceptionResponseContent.
        :type message: str
        """
        self.openapi_types = {"configuration_validation_errors": List[ConfigValidationMessage], "message": str}

        self.attribute_map = {"configuration_validation_errors": "configurationValidationErrors", "message": "message"}

        self._configuration_validation_errors = configuration_validation_errors
        self._message = message

    @classmethod
    def from_dict(cls, dikt) -> "CreateClusterBadRequestExceptionResponseContent":
        """Returns the dict as a model

        :param dikt: A dict.
        :type: dict
        :return: The CreateClusterBadRequestExceptionResponseContent of this
        CreateClusterBadRequestExceptionResponseContent.
        :rtype: CreateClusterBadRequestExceptionResponseContent
        """
        return util.deserialize_model(dikt, cls)

    @property
    def configuration_validation_errors(self):
        """Gets the configuration_validation_errors of this CreateClusterBadRequestExceptionResponseContent.


        :return: The configuration_validation_errors of this CreateClusterBadRequestExceptionResponseContent.
        :rtype: List[ConfigValidationMessage]
        """
        return self._configuration_validation_errors

    @configuration_validation_errors.setter
    def configuration_validation_errors(self, configuration_validation_errors):
        """Sets the configuration_validation_errors of this CreateClusterBadRequestExceptionResponseContent.


        :param configuration_validation_errors: The configuration_validation_errors of this
        CreateClusterBadRequestExceptionResponseContent.
        :type configuration_validation_errors: List[ConfigValidationMessage]
        """

        self._configuration_validation_errors = configuration_validation_errors

    @property
    def message(self):
        """Gets the message of this CreateClusterBadRequestExceptionResponseContent.


        :return: The message of this CreateClusterBadRequestExceptionResponseContent.
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message):
        """Sets the message of this CreateClusterBadRequestExceptionResponseContent.


        :param message: The message of this CreateClusterBadRequestExceptionResponseContent.
        :type message: str
        """

        self._message = message
