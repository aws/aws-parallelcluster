# coding: utf-8

from __future__ import absolute_import

from datetime import date, datetime  # noqa: F401
from typing import Dict, List  # noqa: F401

from pcluster.api import util
from pcluster.api.models.base_model_ import Model
from pcluster.api.models.log_stream import LogStream  # noqa: E501


class ListImageLogStreamsResponseContent(Model):
    """NOTE: This class is auto generated by OpenAPI Generator (https://openapi-generator.tech).

    Do not edit the class manually.
    """

    def __init__(self, log_streams=None, next_token=None):  # noqa: E501
        """ListImageLogStreamsResponseContent - a model defined in OpenAPI

        :param log_streams: The log_streams of this ListImageLogStreamsResponseContent.  # noqa: E501
        :type log_streams: List[LogStream]
        :param next_token: The next_token of this ListImageLogStreamsResponseContent.  # noqa: E501
        :type next_token: str
        """
        self.openapi_types = {"log_streams": List[LogStream], "next_token": str}

        self.attribute_map = {"log_streams": "logStreams", "next_token": "nextToken"}

        self._log_streams = log_streams
        self._next_token = next_token

    @classmethod
    def from_dict(cls, dikt) -> "ListImageLogStreamsResponseContent":
        """Returns the dict as a model

        :param dikt: A dict.
        :type: dict
        :return: The ListImageLogStreamsResponseContent of this ListImageLogStreamsResponseContent.  # noqa: E501
        :rtype: ListImageLogStreamsResponseContent
        """
        return util.deserialize_model(dikt, cls)

    @property
    def log_streams(self):
        """Gets the log_streams of this ListImageLogStreamsResponseContent.


        :return: The log_streams of this ListImageLogStreamsResponseContent.
        :rtype: List[LogStream]
        """
        return self._log_streams

    @log_streams.setter
    def log_streams(self, log_streams):
        """Sets the log_streams of this ListImageLogStreamsResponseContent.


        :param log_streams: The log_streams of this ListImageLogStreamsResponseContent.
        :type log_streams: List[LogStream]
        """
        if log_streams is None:
            raise ValueError("Invalid value for `log_streams`, must not be `None`")  # noqa: E501

        self._log_streams = log_streams

    @property
    def next_token(self):
        """Gets the next_token of this ListImageLogStreamsResponseContent.

        Token to use for paginated requests.  # noqa: E501

        :return: The next_token of this ListImageLogStreamsResponseContent.
        :rtype: str
        """
        return self._next_token

    @next_token.setter
    def next_token(self, next_token):
        """Sets the next_token of this ListImageLogStreamsResponseContent.

        Token to use for paginated requests.  # noqa: E501

        :param next_token: The next_token of this ListImageLogStreamsResponseContent.
        :type next_token: str
        """

        self._next_token = next_token
