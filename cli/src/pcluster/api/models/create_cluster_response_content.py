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
from pcluster.api.models.cluster_info_summary import ClusterInfoSummary
from pcluster.api.models.config_validation_message import ConfigValidationMessage


class CreateClusterResponseContent(Model):
    """NOTE: This class is auto generated by OpenAPI Generator (https://openapi-generator.tech).

    Do not edit the class manually.
    """

    def __init__(self, cluster=None, validation_messages=None):
        """CreateClusterResponseContent - a model defined in OpenAPI

        :param cluster: The cluster of this CreateClusterResponseContent.
        :type cluster: ClusterInfoSummary
        :param validation_messages: The validation_messages of this CreateClusterResponseContent.
        :type validation_messages: List[ConfigValidationMessage]
        """
        self.openapi_types = {"cluster": ClusterInfoSummary, "validation_messages": List[ConfigValidationMessage]}

        self.attribute_map = {"cluster": "cluster", "validation_messages": "validationMessages"}

        self._cluster = cluster
        self._validation_messages = validation_messages

    @classmethod
    def from_dict(cls, dikt) -> "CreateClusterResponseContent":
        """Returns the dict as a model

        :param dikt: A dict.
        :type: dict
        :return: The CreateClusterResponseContent of this CreateClusterResponseContent.
        :rtype: CreateClusterResponseContent
        """
        return util.deserialize_model(dikt, cls)

    @property
    def cluster(self):
        """Gets the cluster of this CreateClusterResponseContent.


        :return: The cluster of this CreateClusterResponseContent.
        :rtype: ClusterInfoSummary
        """
        return self._cluster

    @cluster.setter
    def cluster(self, cluster):
        """Sets the cluster of this CreateClusterResponseContent.


        :param cluster: The cluster of this CreateClusterResponseContent.
        :type cluster: ClusterInfoSummary
        """
        if cluster is None:
            raise ValueError("Invalid value for `cluster`, must not be `None`")

        self._cluster = cluster

    @property
    def validation_messages(self):
        """Gets the validation_messages of this CreateClusterResponseContent.

        List of messages collected during cluster config validation whose level is lower than the validationFailureLevel
        set by the user

        :return: The validation_messages of this CreateClusterResponseContent.
        :rtype: List[ConfigValidationMessage]
        """
        return self._validation_messages

    @validation_messages.setter
    def validation_messages(self, validation_messages):
        """Sets the validation_messages of this CreateClusterResponseContent.

        List of messages collected during cluster config validation whose level is lower than the validationFailureLevel
        set by the user

        :param validation_messages: The validation_messages of this CreateClusterResponseContent.
        :type validation_messages: List[ConfigValidationMessage]
        """
        self._validation_messages = validation_messages
