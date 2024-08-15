import connexion
import six
from typing import Dict
from typing import Tuple
from typing import Union

from pcluster.api.models.bad_request_exception_response_content import BadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.get_cluster_log_events_response_content import GetClusterLogEventsResponseContent  # noqa: E501
from pcluster.api.models.get_cluster_stack_events_response_content import GetClusterStackEventsResponseContent  # noqa: E501
from pcluster.api.models.internal_service_exception_response_content import InternalServiceExceptionResponseContent  # noqa: E501
from pcluster.api.models.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent  # noqa: E501
from pcluster.api.models.list_cluster_log_streams_response_content import ListClusterLogStreamsResponseContent  # noqa: E501
from pcluster.api.models.not_found_exception_response_content import NotFoundExceptionResponseContent  # noqa: E501
from pcluster.api.models.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent  # noqa: E501
from pcluster.api import util


def get_cluster_log_events(cluster_name, log_stream_name, region=None, next_token=None, start_from_head=None, limit=None, start_time=None, end_time=None):  # noqa: E501
    """get_cluster_log_events

    Retrieve the events associated with a log stream. # noqa: E501

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param log_stream_name: Name of the log stream.
    :type log_stream_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str
    :param start_from_head: If the value is true, the earliest log events are returned first. If the value is false, the latest log events are returned first. (Defaults to &#39;false&#39;.)
    :type start_from_head: bool
    :param limit: The maximum number of log events returned. If you don&#39;t specify a value, the maximum is as many log events as can fit in a response size of 1 MB, up to 10,000 log events.
    :type limit: int
    :param start_time: The start of the time range, expressed in ISO 8601 format (e.g. &#39;2021-01-01T20:00:00Z&#39;). Events with a timestamp equal to this time or later than this time are included.
    :type start_time: str
    :param end_time: The end of the time range, expressed in ISO 8601 format (e.g. &#39;2021-01-01T20:00:00Z&#39;). Events with a timestamp equal to or later than this time are not included.
    :type end_time: str

    :rtype: Union[GetClusterLogEventsResponseContent, Tuple[GetClusterLogEventsResponseContent, int], Tuple[GetClusterLogEventsResponseContent, int, Dict[str, str]]
    """
    start_time = util.deserialize_datetime(start_time)
    end_time = util.deserialize_datetime(end_time)
    return 'do some magic!'


def get_cluster_stack_events(cluster_name, region=None, next_token=None):  # noqa: E501
    """get_cluster_stack_events

    Retrieve the events associated with the stack for a given cluster. # noqa: E501

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str

    :rtype: Union[GetClusterStackEventsResponseContent, Tuple[GetClusterStackEventsResponseContent, int], Tuple[GetClusterStackEventsResponseContent, int, Dict[str, str]]
    """
    return 'do some magic!'


def list_cluster_log_streams(cluster_name, region=None, filters=None, next_token=None):  # noqa: E501
    """list_cluster_log_streams

    Retrieve the list of log streams associated with a cluster. # noqa: E501

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: Region that the given cluster belongs to.
    :type region: str
    :param filters: Filter the log streams. Format: &#39;Name&#x3D;a,Values&#x3D;1 Name&#x3D;b,Values&#x3D;2,3&#39;. Accepted filters are: private-dns-name - The short form of the private DNS name of the instance (e.g. ip-10-0-0-101). node-type - The node type, the only accepted value for this filter is HeadNode.
    :type filters: List[str]
    :param next_token: Token to use for paginated requests.
    :type next_token: str

    :rtype: Union[ListClusterLogStreamsResponseContent, Tuple[ListClusterLogStreamsResponseContent, int], Tuple[ListClusterLogStreamsResponseContent, int, Dict[str, str]]
    """
    return 'do some magic!'
