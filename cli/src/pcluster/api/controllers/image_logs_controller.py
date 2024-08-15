import connexion
import six
from typing import Dict
from typing import Tuple
from typing import Union

from pcluster.api.models.bad_request_exception_response_content import BadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.get_image_log_events_response_content import GetImageLogEventsResponseContent  # noqa: E501
from pcluster.api.models.get_image_stack_events_response_content import GetImageStackEventsResponseContent  # noqa: E501
from pcluster.api.models.internal_service_exception_response_content import InternalServiceExceptionResponseContent  # noqa: E501
from pcluster.api.models.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent  # noqa: E501
from pcluster.api.models.list_image_log_streams_response_content import ListImageLogStreamsResponseContent  # noqa: E501
from pcluster.api.models.not_found_exception_response_content import NotFoundExceptionResponseContent  # noqa: E501
from pcluster.api.models.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent  # noqa: E501
from pcluster.api import util


def get_image_log_events(image_id, log_stream_name, region=None, next_token=None, start_from_head=None, limit=None, start_time=None, end_time=None):  # noqa: E501
    """get_image_log_events

    Retrieve the events associated with an image build. # noqa: E501

    :param image_id: Id of the image.
    :type image_id: str
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

    :rtype: Union[GetImageLogEventsResponseContent, Tuple[GetImageLogEventsResponseContent, int], Tuple[GetImageLogEventsResponseContent, int, Dict[str, str]]
    """
    start_time = util.deserialize_datetime(start_time)
    end_time = util.deserialize_datetime(end_time)
    return 'do some magic!'


def get_image_stack_events(image_id, region=None, next_token=None):  # noqa: E501
    """get_image_stack_events

    Retrieve the events associated with the stack for a given image build. # noqa: E501

    :param image_id: Id of the image.
    :type image_id: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str

    :rtype: Union[GetImageStackEventsResponseContent, Tuple[GetImageStackEventsResponseContent, int], Tuple[GetImageStackEventsResponseContent, int, Dict[str, str]]
    """
    return 'do some magic!'


def list_image_log_streams(image_id, region=None, next_token=None):  # noqa: E501
    """list_image_log_streams

    Retrieve the list of log streams associated with an image. # noqa: E501

    :param image_id: Id of the image.
    :type image_id: str
    :param region: Region that the given image belongs to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str

    :rtype: Union[ListImageLogStreamsResponseContent, Tuple[ListImageLogStreamsResponseContent, int], Tuple[ListImageLogStreamsResponseContent, int, Dict[str, str]]
    """
    return 'do some magic!'
