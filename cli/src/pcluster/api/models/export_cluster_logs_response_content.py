# coding: utf-8

from __future__ import absolute_import

from datetime import date, datetime  # noqa: F401
from typing import Dict, List  # noqa: F401

from pcluster.api import util
from pcluster.api.models.base_model_ import Model


class ExportClusterLogsResponseContent(Model):
    """NOTE: This class is auto generated by OpenAPI Generator (https://openapi-generator.tech).

    Do not edit the class manually.
    """

    def __init__(self, log_events_url=None, log_export_task_id=None, message=None, stack_events_url=None):  # noqa: E501
        """ExportClusterLogsResponseContent - a model defined in OpenAPI

        :param log_events_url: The log_events_url of this ExportClusterLogsResponseContent.  # noqa: E501
        :type log_events_url: str
        :param log_export_task_id: The log_export_task_id of this ExportClusterLogsResponseContent.  # noqa: E501
        :type log_export_task_id: str
        :param message: The message of this ExportClusterLogsResponseContent.  # noqa: E501
        :type message: str
        :param stack_events_url: The stack_events_url of this ExportClusterLogsResponseContent.  # noqa: E501
        :type stack_events_url: str
        """
        self.openapi_types = {"log_events_url": str, "log_export_task_id": str, "message": str, "stack_events_url": str}

        self.attribute_map = {
            "log_events_url": "logEventsUrl",
            "log_export_task_id": "logExportTaskId",
            "message": "message",
            "stack_events_url": "stackEventsUrl",
        }

        self._log_events_url = log_events_url
        self._log_export_task_id = log_export_task_id
        self._message = message
        self._stack_events_url = stack_events_url

    @classmethod
    def from_dict(cls, dikt) -> "ExportClusterLogsResponseContent":
        """Returns the dict as a model

        :param dikt: A dict.
        :type: dict
        :return: The ExportClusterLogsResponseContent of this ExportClusterLogsResponseContent.  # noqa: E501
        :rtype: ExportClusterLogsResponseContent
        """
        return util.deserialize_model(dikt, cls)

    @property
    def log_events_url(self):
        """Gets the log_events_url of this ExportClusterLogsResponseContent.

        URL that points to the location of the stored logs.  # noqa: E501

        :return: The log_events_url of this ExportClusterLogsResponseContent.
        :rtype: str
        """
        return self._log_events_url

    @log_events_url.setter
    def log_events_url(self, log_events_url):
        """Sets the log_events_url of this ExportClusterLogsResponseContent.

        URL that points to the location of the stored logs.  # noqa: E501

        :param log_events_url: The log_events_url of this ExportClusterLogsResponseContent.
        :type log_events_url: str
        """
        if log_events_url is None:
            raise ValueError("Invalid value for `log_events_url`, must not be `None`")  # noqa: E501

        self._log_events_url = log_events_url

    @property
    def log_export_task_id(self):
        """Gets the log_export_task_id of this ExportClusterLogsResponseContent.

        Task Id for the log export operation.  # noqa: E501

        :return: The log_export_task_id of this ExportClusterLogsResponseContent.
        :rtype: str
        """
        return self._log_export_task_id

    @log_export_task_id.setter
    def log_export_task_id(self, log_export_task_id):
        """Sets the log_export_task_id of this ExportClusterLogsResponseContent.

        Task Id for the log export operation.  # noqa: E501

        :param log_export_task_id: The log_export_task_id of this ExportClusterLogsResponseContent.
        :type log_export_task_id: str
        """
        if log_export_task_id is None:
            raise ValueError("Invalid value for `log_export_task_id`, must not be `None`")  # noqa: E501

        self._log_export_task_id = log_export_task_id

    @property
    def message(self):
        """Gets the message of this ExportClusterLogsResponseContent.

        Message corresponding to the status of the result of this request.  # noqa: E501

        :return: The message of this ExportClusterLogsResponseContent.
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message):
        """Sets the message of this ExportClusterLogsResponseContent.

        Message corresponding to the status of the result of this request.  # noqa: E501

        :param message: The message of this ExportClusterLogsResponseContent.
        :type message: str
        """
        if message is None:
            raise ValueError("Invalid value for `message`, must not be `None`")  # noqa: E501

        self._message = message

    @property
    def stack_events_url(self):
        """Gets the stack_events_url of this ExportClusterLogsResponseContent.

        URL that points to the location of the stored stack events.  # noqa: E501

        :return: The stack_events_url of this ExportClusterLogsResponseContent.
        :rtype: str
        """
        return self._stack_events_url

    @stack_events_url.setter
    def stack_events_url(self, stack_events_url):
        """Sets the stack_events_url of this ExportClusterLogsResponseContent.

        URL that points to the location of the stored stack events.  # noqa: E501

        :param stack_events_url: The stack_events_url of this ExportClusterLogsResponseContent.
        :type stack_events_url: str
        """
        if stack_events_url is None:
            raise ValueError("Invalid value for `stack_events_url`, must not be `None`")  # noqa: E501

        self._stack_events_url = stack_events_url
