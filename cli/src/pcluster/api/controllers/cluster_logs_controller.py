# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=W0613
import re

import dateutil

from pcluster.api.controllers.common import check_cluster_version, configure_aws_region, convert_errors
from pcluster.api.errors import BadRequestException, NotFoundException
from pcluster.api.models import (
    GetClusterLogEventsResponseContent,
    GetClusterStackEventsResponseContent,
    ListClusterLogStreamsResponseContent,
    LogEvent,
    LogStream,
    StackEvent,
)
from pcluster.aws.common import StackNotFoundError
from pcluster.models.cluster import Cluster
from pcluster.utils import to_iso_time


class _Filter:
    """Class to implement regex parsing for filters parameter."""

    def __init__(self, accepted_filters: list):
        filter_regex = rf"Name=({'|'.join(accepted_filters)}),Values=[\w\-_.,]+"
        self._pattern = re.compile(fr"^({filter_regex})(\s+{filter_regex})*$")

    def __call__(self, value):
        if not self._pattern.match(value):
            raise BadRequestException(f"filters parameter must be in the form {self._pattern.pattern}.")
        return value


def _validate_timestamp(val, ts_name):
    try:
        dateutil.parser.parse(val)
    except Exception:
        raise BadRequestException(
            f"{ts_name} filter must be in the ISO 8601 format: YYYY-MM-DDThh:mm:ssZ. "
            "(e.g. 1984-09-15T19:20:30Z or 1984-09-15)."
        )


@configure_aws_region()
@convert_errors()
def get_cluster_log_events(
    cluster_name,
    log_stream_name,
    region=None,
    next_token=None,
    start_from_head=None,
    limit=None,
    start_time=None,
    end_time=None,
):
    """
    Retrieve the events associated with a log stream.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param log_stream_name: Name of the log stream.
    :type log_stream_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str
    :param start_from_head: If the value is true, the earliest log events are returned first. If the value is false, the
                            latest log events are returned first. (Defaults to &#39;false&#39;.)
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

    :rtype: GetClusterLogEventsResponseContent
    """
    if start_time:
        _validate_timestamp(start_time, "start_time")
    if end_time:
        _validate_timestamp(end_time, "end_time")

    cluster = Cluster(cluster_name)
    try:
        if not check_cluster_version(cluster):
            raise BadRequestException(
                f"cluster '{cluster_name}' belongs to an incompatible ParallelCluster major version."
            )
    except StackNotFoundError:
        raise NotFoundException(
            f"cluster '{cluster_name}' does not exist or belongs to an incompatible ParallelCluster major version."
        )
    log_events = cluster.get_log_events(
        log_stream_name,
        start_time=start_time,
        end_time=end_time,
        start_from_head=start_from_head,
        limit=limit,
        next_token=next_token,
    )

    def convert_log_event(event):
        del event["ingestionTime"]
        event["timestamp"] = to_iso_time(event["timestamp"])
        return LogEvent.from_dict(event)

    events = [convert_log_event(e) for e in log_events.events]
    return GetClusterLogEventsResponseContent(
        events=events, next_token=log_events.next_ftoken, prev_token=log_events.next_btoken
    )


@configure_aws_region()
@convert_errors()
def get_cluster_stack_events(cluster_name, region=None, next_token=None):
    """
    Retrieve the events associated with the stack for a given cluster.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str

    :rtype: GetClusterStackEventsResponseContent
    """
    cluster = Cluster(cluster_name)
    stack_events = cluster.get_stack_events(next_token=next_token)

    def convert_event(event):
        event = {k[0].lower() + k[1:]: v for k, v in event.items()}
        event["timestamp"] = to_iso_time(event["timestamp"])
        return StackEvent.from_dict(event)

    events = [convert_event(event) for event in stack_events["StackEvents"]]
    return GetClusterStackEventsResponseContent(next_token=stack_events.get("NextToken"), events=events)


@configure_aws_region()
@convert_errors()
def list_cluster_log_streams(cluster_name, region=None, filters=None, next_token=None):
    """
    Retrieve the list of log streams associated with a cluster.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: Region that the given cluster belongs to.
    :type region: str
    :param filters: Filter the log streams. Format: (Name&#x3D;a,Values&#x3D;1 Name&#x3D;b,Values&#x3D;2,3).
    :type filters: List[str]
    :param next_token: Token to use for paginated requests.
    :type next_token: str

    :rtype: ListClusterLogStreamsResponseContent
    """
    filter_parser = _Filter(accepted_filters=["private-dns-name", "node-type"])
    filters = [filter_parser(f) for f in filters] if filters else None
    cluster = Cluster(cluster_name)
    try:
        if not check_cluster_version(cluster):
            raise BadRequestException(
                f"cluster '{cluster_name}' belongs to an incompatible ParallelCluster major version."
            )
    except StackNotFoundError:
        raise NotFoundException(
            f"cluster '{cluster_name}' does not exist or belongs to an incompatible ParallelCluster major version. "
        )

    def convert_log(log):
        log["logStreamArn"] = log.pop("arn")
        if "storedBytes" in log:
            del log["storedBytes"]
        for ts_name in ["creationTime", "firstEventTimestamp", "lastEventTimestamp", "lastIngestionTime"]:
            log[ts_name] = to_iso_time(log[ts_name])
        return LogStream.from_dict(log)

    cluster_logs = cluster.list_logs(filters=filters, next_token=next_token)
    log_streams = [convert_log(log) for log in cluster_logs.log_streams]
    next_token = cluster_logs.next_token
    return ListClusterLogStreamsResponseContent(items=log_streams, next_token=next_token)
