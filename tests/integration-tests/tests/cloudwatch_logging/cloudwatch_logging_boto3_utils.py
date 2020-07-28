import json
import logging

import boto3
import utils
from botocore.exceptions import ClientError

LOGGER = logging.getLogger(__name__)


def _dumps_json(obj):
    """Dump obj to a JSON string."""
    return json.dumps(obj, indent=2)


def get_cluster_log_groups_from_boto3(cluster_log_group_prefix):
    """
    Get log groups with cluster log group prefix from boto3.

    Raises ClientError.
    """
    try:
        log_groups = (
            boto3.client("logs").describe_log_groups(logGroupNamePrefix=cluster_log_group_prefix).get("logGroups")
        )
        LOGGER.debug("Log groups: {0}\n".format(_dumps_json(log_groups)))
        return log_groups
    except ClientError as e:
        LOGGER.debug("Unable to retrieve any log group with prefix {0}\nError: {1}".format(cluster_log_group_prefix, e))
        raise ClientError


def get_log_streams(log_group_name):
    """
    Get list of log streams.

    Raises ClientError if the log group doesn't exist.
    """
    streams = boto3.client("logs").describe_log_streams(logGroupName=log_group_name).get("logStreams")
    LOGGER.debug("Log streams for {group}:\n{streams}".format(group=log_group_name, streams=_dumps_json(streams)))
    return streams


def get_log_events(log_group_name, log_stream_name):
    """
    Get log events for the given log_stream_name.

    Raises ClientError if the given log group or stream doesn't exist.
    """
    logs_client = boto3.client("logs")
    events = logs_client.get_log_events(logGroupName=log_group_name, logStreamName=log_stream_name).get("events")
    LOGGER.debug(
        "Log events for {group}/{stream}:\n{events}".format(
            group=log_group_name, stream=log_stream_name, events=_dumps_json(events)
        )
    )
    return events


def get_ec2_instances():
    """Iterate through ec2's describe_instances."""
    for instance_page in utils.paginate_boto3(boto3.client("ec2").describe_instances):
        for instance in instance_page.get("Instances"):
            yield instance


def _get_log_group_for_stack(stack_name):
    """Return a list of log groups belonging to the given stack."""
    log_groups = []
    for resource in utils.get_cfn_resources(stack_name):
        if resource.get("ResourceType") == "AWS::Logs::LogGroup":
            log_groups.append(resource.get("PhysicalResourceId"))
    return log_groups


def get_cluster_log_groups(stack_name):
    """Return list of PhysicalResourceIds for log groups created by cluster with given stack name."""
    log_groups = []
    substack_phys_ids = utils.get_substacks(stack_name)
    for substack_phys_id in substack_phys_ids:
        log_groups.extend(_get_log_group_for_stack(substack_phys_id))
    return log_groups


def delete_log_group(log_group):
    """Delete the given log group."""
    try:
        boto3.client("logs").delete_log_group(logGroupName=log_group)
    except ClientError as client_err:
        if client_err.response.get("Error").get("Code") == "ResourceNotFoundException":
            return  # Log group didn't exist.
        LOGGER.warning(
            "Error when deleting log group {log_group}: {msg}".format(
                log_group=log_group, msg=client_err.response.get("Error").get("Message")
            )
        )


def delete_log_groups(log_groups):
    """Delete the given log groups, if they exist."""
    for log_group in log_groups:
        delete_log_group(log_group)
