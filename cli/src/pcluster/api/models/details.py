# coding: utf-8

from __future__ import absolute_import

from datetime import date, datetime  # noqa: F401
from typing import Dict, List  # noqa: F401

from pcluster.api import util
from pcluster.api.models.alarm import Alarm  # noqa: E501
from pcluster.api.models.base_model_ import Model
from pcluster.api.models.metric import Metric  # noqa: E501
from pcluster.api.models.stat import Stat  # noqa: E501


class Details(Model):
    """NOTE: This class is auto generated by OpenAPI Generator (https://openapi-generator.tech).

    Do not edit the class manually.
    """

    def __init__(self, alarms=None, metrics=None, stats=None):  # noqa: E501
        """Details - a model defined in OpenAPI

        :param alarms: The alarms of this Details.  # noqa: E501
        :type alarms: List[Alarm]
        :param metrics: The metrics of this Details.  # noqa: E501
        :type metrics: List[Metric]
        :param stats: The stats of this Details.  # noqa: E501
        :type stats: List[Stat]
        """
        self.openapi_types = {"alarms": List[Alarm], "metrics": List[Metric], "stats": List[Stat]}

        self.attribute_map = {"alarms": "alarms", "metrics": "metrics", "stats": "stats"}

        self._alarms = alarms
        self._metrics = metrics
        self._stats = stats

    @classmethod
    def from_dict(cls, dikt) -> "Details":
        """Returns the dict as a model

        :param dikt: A dict.
        :type: dict
        :return: The Details of this Details.  # noqa: E501
        :rtype: Details
        """
        return util.deserialize_model(dikt, cls)

    @property
    def alarms(self):
        """Gets the alarms of this Details.

        List of alarms when the verbose flag is set to true.  # noqa: E501

        :return: The alarms of this Details.
        :rtype: List[Alarm]
        """
        return self._alarms

    @alarms.setter
    def alarms(self, alarms):
        """Sets the alarms of this Details.

        List of alarms when the verbose flag is set to true.  # noqa: E501

        :param alarms: The alarms of this Details.
        :type alarms: List[Alarm]
        """

        self._alarms = alarms

    @property
    def metrics(self):
        """Gets the metrics of this Details.

        List of metrics when the verbose flag is set to true.  # noqa: E501

        :return: The metrics of this Details.
        :rtype: List[Metric]
        """
        return self._metrics

    @metrics.setter
    def metrics(self, metrics):
        """Sets the metrics of this Details.

        List of metrics when the verbose flag is set to true.  # noqa: E501

        :param metrics: The metrics of this Details.
        :type metrics: List[Metric]
        """

        self._metrics = metrics

    @property
    def stats(self):
        """Gets the stats of this Details.

        Statistics about the cluster, like the number of running compute nodes.  # noqa: E501

        :return: The stats of this Details.
        :rtype: List[Stat]
        """
        return self._stats

    @stats.setter
    def stats(self, stats):
        """Sets the stats of this Details.

        Statistics about the cluster, like the number of running compute nodes.  # noqa: E501

        :param stats: The stats of this Details.
        :type stats: List[Stat]
        """

        self._stats = stats
