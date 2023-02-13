# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=W0613

from pcluster.api.controllers.common import (
    assert_supported_operation,
    configure_aws_region,
    convert_errors,
    validate_timestamp,
)
from pcluster.api.errors import BadRequestException
from pcluster.api.models import (
    GetImageLogEventsResponseContent,
    GetImageStackEventsResponseContent,
    ListImageLogStreamsResponseContent,
    LogEvent,
    LogStream,
    StackEvent,
)
from pcluster.constants import Operation
from pcluster.models.imagebuilder import ImageBuilder
from pcluster.utils import to_iso_timestr, to_utc_datetime


@configure_aws_region()
@convert_errors()
def get_image_log_events(
    image_id,
    log_stream_name,
    region=None,
    next_token=None,
    start_from_head=None,
    limit=None,
    start_time: str = None,
    end_time: str = None,
):
    """
    Retrieve the events associated with an image build.

    :param image_id: Id of the image.
    :type image_id: str
    :param log_stream_name: Name of the log stream.
    :type log_stream_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str
    :param start_from_head: If the value is true, the earliest log events are returned first. If the value is false,
                            the latest log events are returned first. (Defaults to &#39;false&#39;.)
    :type start_from_head: bool
    :param limit: The maximum number of log events returned. If you don&#39;t specify a value, the maximum is as many
                  log events as can fit in a response size of 1 MB, up to 10,000 log events.
    :type limit:
    :param start_time: The start of the time range, expressed in ISO 8601 format
                       (e.g. &#39;2021-01-01T20:00:00Z&#39;). Events with a timestamp equal to this time or later
                       than this time are included.
    :type start_time: str
    :param end_time: The end of the time range, expressed in ISO 8601 format (e.g. &#39;2021-01-01T20:00:00Z&#39;).
                     Events with a timestamp equal to or later than this time are not included.
    :type end_time: str

    :rtype: GetImageLogEventsResponseContent
    """
    assert_supported_operation(operation=Operation.GET_IMAGE_LOG_EVENTS, region=region)
    start_dt = start_time and validate_timestamp(start_time, "start_time")
    end_dt = end_time and validate_timestamp(end_time, "end_time")

    if start_time and end_time and start_dt >= end_dt:
        raise BadRequestException("start_time filter must be earlier than end_time filter.")

    if limit and limit <= 0:
        raise BadRequestException("'limit' must be a positive integer.")

    imagebuilder = ImageBuilder(image_id=image_id)
    log_events = imagebuilder.get_log_events(
        log_stream_name,
        start_time=start_dt,
        end_time=end_dt,
        start_from_head=start_from_head,
        limit=limit,
        next_token=next_token,
    )

    def convert_log_event(event):
        del event["ingestionTime"]
        event["timestamp"] = to_iso_timestr(to_utc_datetime(event["timestamp"]))
        return LogEvent.from_dict(event)

    events = [convert_log_event(e) for e in log_events.events]
    return GetImageLogEventsResponseContent(
        events=events, next_token=log_events.next_ftoken, prev_token=log_events.next_btoken
    )


@configure_aws_region()
@convert_errors()
def get_image_stack_events(image_id, region=None, next_token=None):
    """
    Retrieve the events associated with the stack for a given image build.

    :param image_id: Id of the image.
    :type image_id: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str

    :rtype: GetImageStackEventsResponseContent
    """
    assert_supported_operation(operation=Operation.GET_IMAGE_STACK_EVENTS, region=region)
    imagebuilder = ImageBuilder(image_id=image_id)
    stack_events = imagebuilder.get_stack_events(next_token=next_token)

    def convert_event(event):
        event = {k[0].lower() + k[1:]: v for k, v in event.items()}
        event["timestamp"] = to_iso_timestr(to_utc_datetime(event["timestamp"]))
        return StackEvent.from_dict(event)

    events = [convert_event(event) for event in stack_events["StackEvents"]]
    return GetImageStackEventsResponseContent(next_token=stack_events.get("NextToken", None), events=events)


@configure_aws_region()
@convert_errors()
def list_image_log_streams(image_id, region=None, next_token=None):
    """
    Retrieve the list of log streams associated with an image.

    :param image_id: Id of the image.
    :type image_id: str
    :param region: Region that the given image belongs to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str

    :rtype: ListImageLogStreamsResponseContent
    """

    def convert_log(log):
        log["logStreamArn"] = log.pop("arn")
        if "storedBytes" in log:
            del log["storedBytes"]
        for ts_name in ["creationTime", "firstEventTimestamp", "lastEventTimestamp", "lastIngestionTime"]:
            log[ts_name] = to_iso_timestr(to_utc_datetime(log[ts_name]))
        return LogStream.from_dict(log)

    assert_supported_operation(operation=Operation.LIST_IMAGE_LOG_STREAMS, region=region)
    imagebuilder = ImageBuilder(image_id=image_id)
    logs = imagebuilder.list_log_streams(next_token=next_token)
    log_streams = [convert_log(log) for log in logs.log_streams]
    next_token = logs.next_token
    return ListImageLogStreamsResponseContent(log_streams=log_streams, next_token=next_token)
