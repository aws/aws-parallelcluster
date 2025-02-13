# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import datetime
import json
import logging
import re
import tarfile
import tempfile
import time

import boto3
import botocore
import pytest
from assertpy import assert_that
from dateutil.parser import parse as date_parse
from framework.credential_providers import run_pcluster_command
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from utils import (
    check_pcluster_list_cluster_log_streams,
    check_status,
    get_cluster_nodes_instance_ids,
    instance_stream_name,
)

from tests.common.assertions import assert_no_errors_in_logs, wait_for_num_instances_in_cluster
from tests.common.utils import get_installed_parallelcluster_version, retrieve_latest_ami


@pytest.mark.usefixtures("instance")
def test_slurm_cli_commands(
    request, scheduler, region, os, pcluster_config_reader, clusters_factory, s3_bucket_factory
):
    """Test pcluster cli commands are working."""
    # Use long scale down idle time so we know nodes are terminated by pcluster stop
    cluster_config = pcluster_config_reader(scaledown_idletime=60)

    if "alinux" in os or "us-iso" not in region:  # The code does not know non-amazon vanilla AMIs IDs in iso regions
        # Using custom AMI not tagged by pcluser will generate a warning
        custom_ami = retrieve_latest_ami(region, os, ami_type="official", architecture="x86_64")
        config_file = "pcluster.config.with.warnings.yaml"
        cluster_config_with_warning = pcluster_config_reader(config_file=config_file, custom_ami=custom_ami)

        # Test below is not compatible with `--cluster` flag. Therefore, skip it if the flag is provided.
        if not request.config.getoption("cluster"):
            _test_create_with_warnings(cluster_config_with_warning, clusters_factory)

    cluster = _test_create_cluster(clusters_factory, cluster_config, request)
    _test_describe_cluster(cluster)
    _test_list_cluster(cluster.name, "CREATE_COMPLETE")

    if "alinux" in os or "us-iso" not in region:
        _test_update_with_warnings(cluster_config_with_warning, cluster)
    check_status(cluster, "CREATE_COMPLETE", "running", "RUNNING")

    filters = [{}, {"node_type": "HeadNode"}, {"node_type": "Compute"}, {"queue_name": "ondemand1"}]
    for filter_ in filters:
        _test_describe_instances(cluster, **filter_)
    _test_pcluster_export_cluster_logs(s3_bucket_factory, cluster)
    _test_pcluster_export_cluster_logs(s3_bucket_factory, cluster, True)
    check_pcluster_list_cluster_log_streams(cluster, os)
    _test_pcluster_get_cluster_log_events(cluster)
    _test_pcluster_get_cluster_stack_events(cluster)
    _test_pcluster_compute_fleet(cluster, expected_num_nodes=2)

    remote_command_executor = RemoteCommandExecutor(cluster)
    assert_no_errors_in_logs(remote_command_executor, scheduler)


def _test_create_cluster(clusters_factory, cluster_config, request):
    cluster = clusters_factory(cluster_config, wait=False)
    if request.config.getoption("cluster"):
        return cluster

    expected_creation_response = {
        "clusterName": cluster.name,
        "cloudformationStackStatus": "CREATE_IN_PROGRESS",
        "cloudformationStackArn": cluster.cfn_stack_arn,
        "region": cluster.region,
        "version": get_installed_parallelcluster_version(),
        "clusterStatus": "CREATE_IN_PROGRESS",
        "scheduler": {"type": "slurm"},
    }
    assert_that(cluster.creation_response.get("cluster")).is_equal_to(expected_creation_response)
    _test_list_cluster(cluster.name, "CREATE_IN_PROGRESS")
    logging.info("Waiting for CloudFormation stack creation completion")
    cloud_formation = boto3.client("cloudformation")
    waiter = cloud_formation.get_waiter("stack_create_complete")
    waiter.wait(StackName=cluster.name)
    return cluster


def _test_create_with_warnings(cluster_config, clusters_factory):
    def run_fn(extra_args):
        return clusters_factory(cluster_config, **extra_args).creation_response

    _test_create_or_update_with_warnings(run_fn)


def _test_update_with_warnings(cluster_config, cluster):
    def run_fn(extra_args):
        response = cluster.update(cluster_config, force_update="true", **extra_args)
        if response["message"].startswith("Request would have succeeded"):
            assert_that(response).contains("changeSet")
        else:
            assert_that(response).does_not_contain("changeSet")
        return response

    _test_create_or_update_with_warnings(run_fn)


def _validation_test_cases():
    """Generates the test-case data for performing create / update operations with errors, suppresssion and dryrun."""

    def _args(*suppressed_validators, dryrun=True, failure_level="WARNING"):
        """Converts the supplied options into a dict that will be used for the parameters to the command."""
        suppress_arg = {"suppress_validators": suppressed_validators} if suppressed_validators else {}
        failure_arg = {"validation_failure_level": failure_level} if failure_level else {}
        return {"dryrun": dryrun, **failure_arg, **suppress_arg}

    def _test_case(success, validation_messages, args):
        """Return a tuple of expected, key for the messages in the response, args"""
        if success:
            message = "Request would have succeeded, but DryRun flag is set."
        else:
            message = "Invalid cluster configuration."
        messages_key = "validationMessages" if success else "configurationValidationErrors"
        expected_validation_response = {messages_key: validation_messages} if validation_messages else {}
        return ({**expected_validation_response, "message": message}, messages_key, args)

    # expected individual warning / error messages
    custom_ami_warning = {
        "level": "WARNING",
        "type": "CustomAmiTagValidator",
        "message": "The custom AMI may not.*been created by pcluster",
    }
    name_error = {
        "level": "ERROR",
        "type": "NameValidator",
        "message": "Name must begin with a letter and only contain lowercase letters, digits and hyphens.",
    }
    key_pair_warning = {"level": "WARNING", "type": "KeyPairValidator", "message": ".*you do not specify a key pair.*"}
    ami_os_compatibility = {
        "level": "WARNING",
        "type": "AmiOsCompatibleValidator",
        "message": "Could not check node AMI*OS and cluster OS*compatibility,",
    }

    all_invalid = [custom_ami_warning, key_pair_warning, name_error, ami_os_compatibility]
    warnings = [custom_ami_warning, key_pair_warning, ami_os_compatibility]
    suppressed = [key_pair_warning, ami_os_compatibility]
    no_warnings = []
    all_suppressors = ["type:%s" % warning["type"] for warning in all_invalid]
    success, fail = True, False

    return [
        _test_case(fail, all_invalid, _args(dryrun=False, failure_level=None)),  # default failure level
        _test_case(fail, all_invalid, _args(dryrun=False)),  # warning failure level
        _test_case(fail, all_invalid, _args()),  # dryrun without any suppression
        _test_case(fail, suppressed, _args("type:CustomAmiTagValidator", "type:NameValidator")),  # suppress some
        _test_case(success, warnings, _args("type:NameValidator", failure_level=None)),  # suppress the error
        _test_case(success, no_warnings, _args(*all_suppressors)),  # suppressor for each warning
        _test_case(success, no_warnings, _args("ALL")),  # the "ALL" suppressor
    ]


def _test_create_or_update_with_warnings(run_fn):
    """
    Test create-cluster or update-cluster with a erroneous configuration file.

    Accepts a run_fn function that will accept arguments for create / update
    """
    for expected_response, validation_key, args in _validation_test_cases():
        actual_response = run_fn({"raise_on_error": False, "log_error": False, **args})
        _check_response(actual_response, expected_response, validation_key)


def _check_response(actual_response, expected_response, validation_key):
    expected_errors = {err["type"]: err for err in expected_response.get(validation_key, [])}
    actual_errors = {err["type"]: err for err in actual_response.get(validation_key, [])}
    assert_that(actual_errors).is_length(len(expected_errors))
    for err_type, expected_err in expected_errors.items():
        assert_that(actual_errors).contains(err_type)
        actual_err = actual_errors[err_type]
        assert_that(re.search(expected_err["message"], actual_err["message"]))
        assert_that(actual_err).is_equal_to(expected_err, ignore="message")

    assert_that(actual_response).is_equal_to(expected_response, ignore=[validation_key, "changeSet"])


def _test_describe_cluster(cluster):
    cluster_info = cluster.describe_cluster()
    assert_that(cluster_info).is_not_none()
    assert_that(cluster_info).contains("clusterName")
    assert_that(cluster_info).contains("clusterStatus")
    assert_that(cluster_info).contains("region")
    assert_that(cluster_info).contains("clusterStatus")
    assert_that(cluster_info).contains("cloudformationStackArn")
    assert_that(cluster_info).contains("creationTime")
    assert_that(cluster_info).contains("clusterConfiguration")
    assert_that(cluster_info).contains("scheduler")
    assert_that(cluster_info).contains("loginNodes")


def _test_list_cluster(cluster_name, expected_status):
    # Test the command response contains the cluster_name and expected_status.
    # ToDo: design test for this command to check stacks inside a region.
    #  It is hard because the test will be dependent on other tests
    logging.info("Testing list clusters")
    cmd_args = ["pcluster", "list-clusters"]
    found_cluster = _find_cluster_with_pagination(cmd_args, cluster_name)
    assert_that(found_cluster).is_not_none()
    assert_that(found_cluster["cloudformationStackStatus"]).is_equal_to(expected_status)

    logging.info("Testing list clusters with status filter")
    cmd_args.extend(["--cluster-status", expected_status])
    found_cluster = _find_cluster_with_pagination(cmd_args, cluster_name)
    assert_that(found_cluster).is_not_none()
    assert_that(found_cluster["cloudformationStackStatus"]).is_equal_to(expected_status)
    assert_that(found_cluster["scheduler"]).is_equal_to({"type": "slurm"})


def _find_cluster_with_pagination(cmd_args, cluster_name):
    result = run_pcluster_command(cmd_args)
    response = json.loads(result.stdout)
    found_cluster = _find_cluster_in_list(cluster_name, response["clusters"])
    while response.get("nextToken") and found_cluster is None:
        cmd_args_with_next_token = cmd_args + ["--next-token", response["nextToken"]]
        result = run_pcluster_command(cmd_args_with_next_token)
        response = json.loads(result.stdout)
        found_cluster = _find_cluster_in_list(cluster_name, response["clusters"])
    return found_cluster


def _find_cluster_in_list(cluster_name, cluster_list):
    return next(filter(lambda c: c["clusterName"] == cluster_name, cluster_list), None)


def _test_describe_instances(cluster, node_type=None, queue_name=None):
    logging.info("Testing the result from describe-cluster-instances is the same as calling boto3 directly.")
    cluster_instances_from_ec2 = get_cluster_nodes_instance_ids(
        cluster.cfn_name, cluster.region, node_type=node_type, queue_name=queue_name
    )
    cluster_instances_from_cli = cluster.get_cluster_instance_ids(node_type=node_type, queue_name=queue_name)
    assert_that(set(cluster_instances_from_cli)).is_equal_to(set(cluster_instances_from_ec2))


def _test_pcluster_compute_fleet(cluster, expected_num_nodes):
    """Test pcluster compute fleet commands."""
    logging.info("Testing pcluster stop functionalities")
    cluster.stop()
    # Sample pcluster stop output:
    # Compute fleet status is: RUNNING. Submitting status change request.
    # Request submitted successfully. It might take a while for the transition to complete.
    # Please run 'pcluster status' if you need to check compute fleet status

    wait_for_num_instances_in_cluster(cluster.cfn_name, cluster.region, desired=0)
    _test_describe_instances(cluster)
    compute_fleet = cluster.describe_compute_fleet()
    assert_that(compute_fleet["status"]).is_equal_to("STOPPED")
    last_stop_time = compute_fleet["lastStatusUpdatedTime"]

    logging.info("Testing pcluster start functionalities")
    # Do a complicated sequence of start and stop and see if commands will still work
    cluster.start()
    time.sleep(15)
    cluster.stop()
    time.sleep(15)
    cluster.stop()
    time.sleep(30)
    cluster.start()
    compute_fleet = cluster.describe_compute_fleet()
    last_start_time = compute_fleet["lastStatusUpdatedTime"]
    logging.info("Checking last status update time is updated")
    assert_that(last_stop_time < last_start_time)
    wait_for_num_instances_in_cluster(cluster.cfn_name, cluster.region, desired=expected_num_nodes)
    _test_describe_instances(cluster)
    check_status(cluster, "CREATE_COMPLETE", "running", "RUNNING")


def _test_export_log_files_are_expected(cluster, bucket_name, instance_ids, bucket_prefix, filters=None):
    # test with a prefix and an output file
    with tempfile.TemporaryDirectory() as tempdir:
        output_file = f"{tempdir}/testfile.tar.gz"
        ret = cluster.export_logs(
            bucket=bucket_name, output_file=output_file, bucket_prefix=bucket_prefix, filters=filters
        )
        assert_that(ret["path"]).is_equal_to(output_file)

        with tarfile.open(output_file) as archive:
            filenames = {logfile.name for logfile in archive}

            # check there are the logs of all the instances and cfn logs
            for file_expected in set(instance_ids) | {f"{cluster.name}-cfn-events"}:
                assert_that(any(file_expected in filename for filename in filenames)).is_true()


def _test_pcluster_export_cluster_logs(s3_bucket_factory, cluster, use_pcluster_bucket=False):
    """Test pcluster export-cluster-logs functionality."""
    instance_ids = cluster.get_cluster_instance_ids()
    headnode_instance_id = cluster.get_cluster_instance_ids(node_type="HeadNode")

    logging.info("Testing that pcluster export-cluster-logs is working as expected")

    if not use_pcluster_bucket:
        bucket_name = s3_bucket_factory()
        logging.info("bucket is %s", bucket_name)

        # set bucket permissions
        bucket_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "s3:GetBucketAcl",
                    "Effect": "Allow",
                    "Resource": f"arn:{cluster.partition}:s3:::{bucket_name}",
                    "Principal": {"Service": f"logs.{cluster.region}.amazonaws.com"},
                },
                {
                    "Action": "s3:PutObject",
                    "Effect": "Allow",
                    "Resource": f"arn:{cluster.partition}:s3:::{bucket_name}/*",
                    "Condition": {"StringEquals": {"s3:x-amz-acl": "bucket-owner-full-control"}},
                    "Principal": {"Service": f"logs.{cluster.region}.amazonaws.com"},
                },
            ],
        }
        boto3.client("s3").put_bucket_policy(Bucket=bucket_name, Policy=json.dumps(bucket_policy))
    else:
        bucket_name = cluster.cfn_parameters.get("ResourcesS3Bucket")
        logging.info("Using pcluster bucket %s.", bucket_name)

    # test with a prefix and an output file
    bucket_prefix = "test_prefix"
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(3))(_test_export_log_files_are_expected)(
        cluster, bucket_name if not use_pcluster_bucket else None, instance_ids, bucket_prefix
    )

    # test export-cluster-logs with filter option
    retry(wait_fixed=seconds(20), stop_max_delay=minutes(3))(_test_export_log_files_are_expected)(
        cluster,
        bucket_name if not use_pcluster_bucket else None,
        headnode_instance_id,
        bucket_prefix,
        filters="Name=node-type,Values=HeadNode",
    )

    # check bucket_prefix folder has been removed from S3
    bucket_cleaned_up = False
    try:
        boto3.resource("s3").Object(bucket_name, bucket_prefix).load()
    except botocore.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            bucket_cleaned_up = True
    assert_that(bucket_cleaned_up).is_true()

    # test without a prefix or output file
    ret = cluster.export_logs(bucket=bucket_name if not use_pcluster_bucket else None)
    assert_that(ret).contains_key("url")
    filename = ret["url"].split(".tar.gz")[0].split("/")[-1] + ".tar.gz"
    archive_found = True
    try:
        boto3.resource("s3").Object(bucket_name, filename).load()
    except botocore.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            archive_found = False
    assert_that(archive_found).is_true()


def _test_pcluster_get_cluster_log_events(cluster):
    """Test pcluster get-cluster-log-events functionality."""
    logging.info("Testing that pcluster get-cluster-log-events is working as expected")
    cluster_info = cluster.describe_cluster()
    cfn_init_log_stream = instance_stream_name(cluster_info["headNode"], "cfn-init")

    # Get the first event to establish time boundary for testing
    initial_events = cluster.get_log_events(cfn_init_log_stream, limit=1, start_from_head=True)
    first_event = initial_events["events"][0]
    first_event_time_str = first_event["timestamp"]
    first_event_time = date_parse(first_event_time_str)
    before_first = (first_event_time - datetime.timedelta(seconds=1)).isoformat()
    after_first = (first_event_time + datetime.timedelta(seconds=1)).isoformat()

    # args, expect_first, expect_count
    test_cases = [
        ({}, None, None),
        ({"limit": 1}, False, 1),
        ({"limit": 2, "start_from_head": True}, True, 2),
        ({"limit": 1, "start_time": before_first, "end_time": after_first, "start_from_head": True}, True, 1),
        ({"limit": 1, "end_time": before_first}, None, 0),
        ({"limit": 1, "start_time": after_first, "start_from_head": True}, False, 1),
        ({"limit": 1, "next_token": initial_events["nextToken"]}, False, 1),
        ({"limit": 1, "next_token": initial_events["nextToken"], "start_from_head": True}, False, 1),
    ]

    for args, expect_first, expect_count in test_cases:
        events = cluster.get_log_events(cfn_init_log_stream, **args)["events"]

        if expect_count is not None:
            assert_that(events).is_length(expect_count)

        if expect_first is True:
            assert_that(events[0]["message"]).is_equal_to(first_event["message"])

        if expect_first is False:
            assert_that(events[0]["message"]).is_not_equal_to(first_event["message"])


def _test_pcluster_get_cluster_stack_events(cluster):
    logging.info("Testing that pcluster get-cluster-stack-events is working as expected")
    stack_events_resp = cluster.get_stack_events()
    assert_that(stack_events_resp).is_not_none()
    assert_that(stack_events_resp).contains("events")
    assert_that(stack_events_resp["events"]).is_not_empty()

    first_event = stack_events_resp["events"][0]
    assert_that(first_event).contains("eventId")
    assert_that(first_event).contains("logicalResourceId")
    assert_that(first_event).contains("physicalResourceId")
    assert_that(first_event).contains("stackId")
    assert_that(first_event).contains("timestamp")
