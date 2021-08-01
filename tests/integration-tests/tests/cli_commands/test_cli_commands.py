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
from dateutil.parser import parse as date_parse

import boto3
import botocore
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from utils import check_status, get_cluster_nodes_instance_ids, run_command

from tests.common.assertions import assert_no_errors_in_logs, wait_for_num_instances_in_cluster
from tests.common.utils import get_installed_parallelcluster_version, retrieve_latest_ami


def instance_stream_name(instance, stream_name):
    "Return a stream name given an instance."
    ip_str = instance["privateIpAddress"].replace(".", "-")
    return "ip-{}.{}.{}".format(ip_str, instance["instanceId"], stream_name)


@pytest.mark.regions(["us-east-2"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.oss(["ubuntu1804"])
@pytest.mark.usefixtures("region", "instance")
def test_slurm_cli_commands(
    request, scheduler, region, os, pcluster_config_reader, clusters_factory, s3_bucket_factory
):
    """Test pcluster cli commands are working."""
    # Use long scale down idle time so we know nodes are terminated by pcluster stop
    cluster_config = pcluster_config_reader(scaledown_idletime=60)
    # Generate configuration with warnings and errors
    custom_ami = retrieve_latest_ami(
        region, os, ami_type="official", architecture="x86_64"
    )  # Using custom AMI not tagged by pcluser will generate a warning
    cluster_config_with_warning = pcluster_config_reader(
        config_file="pcluster.config.with.warnings.yaml", custom_ami=custom_ami
    )
    cluster = _test_create_cluster(clusters_factory, cluster_config, cluster_config_with_warning, request)

    _test_describe_cluster(cluster)
    _test_list_cluster(cluster.name, "CREATE_COMPLETE")
    _test_create_or_update_with_warnings(str(cluster_config_with_warning), cluster=cluster)
    check_status(cluster, "CREATE_COMPLETE", "running", "RUNNING")

    _test_describe_instances(cluster)
    _test_describe_instances(cluster, node_type="HeadNode")
    _test_describe_instances(cluster, node_type="Compute")
    _test_describe_instances(cluster, queue_name="ondemand1")
    _test_pcluster_compute_fleet(cluster, expected_num_nodes=2)
    _test_pcluster_export_cluster_logs(s3_bucket_factory, cluster)
    _test_pcluster_list_cluster_log_streams(cluster)
    _test_pcluster_get_cluster_log_events(cluster)
    _test_pcluster_get_cluster_stack_events(cluster)

    remote_command_executor = RemoteCommandExecutor(cluster)
    assert_no_errors_in_logs(remote_command_executor, scheduler)


def _test_create_cluster(clusters_factory, cluster_config, cluster_config_with_warning, request):
    if not request.config.getoption("cluster"):
        # Test below is not compatible with `--cluster` flag. Therefore, skip it if the flag is provided.
        _test_create_or_update_with_warnings(cluster_config_with_warning, clusters_factory)

    cluster = clusters_factory(cluster_config, wait=False)
    if not request.config.getoption("cluster"):
        expected_creation_response = {
            "cluster": {
                "clusterName": cluster.name,
                "cloudformationStackStatus": "CREATE_IN_PROGRESS",
                "cloudformationStackArn": cluster.cfn_stack_arn,
                "region": cluster.region,
                "version": get_installed_parallelcluster_version(),
                "clusterStatus": "CREATE_IN_PROGRESS",
            }
        }
        assert_that(cluster.creation_response).is_equal_to(expected_creation_response)
        _test_list_cluster(cluster.name, "CREATE_IN_PROGRESS")
        logging.info("Waiting for CloudFormation stack creation completion")
        cloud_formation = boto3.client("cloudformation")
        waiter = cloud_formation.get_waiter("stack_create_complete")
        waiter.wait(StackName=cluster.name)
    return cluster


def _test_create_or_update_with_warnings(cluster_config_with_warning, clusters_factory=None, cluster=None):
    """
    Test create-cluster or update-cluster with a erroneous configuration file.

    If clusters_factory is not None, this function tests create-cluster.
    Otherwise cluster has to be provided and this function tests update-cluster.
    """
    # clusters_factory and cluster are mutually exclusive but one of them has to be provided
    assert_that(clusters_factory or cluster).is_not_none()
    logging.info("Testing cluster creation/update on a configuration file with 1 error and 2 warnings.")
    custom_ami_tag_warning = {
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

    test_cases = []

    def construct_validation_error_expected_response(configuration_validation_errors):
        return {
            "configurationValidationErrors": configuration_validation_errors,
            "message": "Invalid cluster configuration",
        }

    expected_response = construct_validation_error_expected_response(
        [custom_ami_tag_warning, key_pair_warning, name_error]
    )
    test_cases.extend(
        [
            (expected_response, ["--validation-failure-level", "WARNING"]),
            (expected_response, ["--validation-failure-level", "WARNING", "--dryrun", "true"]),
            # Test default --validation-failure-level shows errors and warnings
            (expected_response, None),
        ]
    )

    # Test suppressing a error and a warning
    expected_response = construct_validation_error_expected_response([key_pair_warning])
    test_cases.append(
        (
            expected_response,
            [
                "--validation-failure-level",
                "WARNING",
                "--dryrun",
                "true",
                "--suppress-validators",
                "type:CustomAmiTagValidator",
                "type:NameValidator",
            ],
        )
    )

    # Test dry run with successful validations
    # Test default --validation-failure-level does not fail on warnings
    expected_response = {"message": "Request would have succeeded, but DryRun flag is set."}
    test_cases.extend(
        [
            (expected_response, ["--dryrun", "true", "--suppress-validators", "type:NameValidator"]),
            (
                expected_response,
                [
                    "--validation-failure-level",
                    "WARNING",
                    "--dryrun",
                    "true",
                    "--suppress-validators",
                    "type:CustomAmiTagValidator",
                    "type:NameValidator",
                    "type:KeyPairValidator",
                ],
            ),
            # Test suppressing all validators
            (
                expected_response,
                ["--validation-failure-level", "WARNING", "--dryrun", "true", "--suppress-validators", "ALL"],
            ),
        ]
    )
    for test_case in test_cases:
        _check_response(
            cluster_config_with_warning,
            test_case[0],
            extra_args=test_case[1],
            clusters_factory=clusters_factory,
            cluster=cluster,
        )


def _create_cluster_with_warnings(clusters_factory, cluster_config, extra_args=None):
    """
    Create cluster with warnings expected.

    Set log_error=False and raise_on_error=False if error is expected.
    Therefore, the test log won't be flooded with errors.
    """
    return clusters_factory(
        cluster_config, extra_args=extra_args, raise_on_error=False, wait=False, log_error=False
    ).creation_response


def _check_response(cluster_config, expected_response, clusters_factory=None, cluster=None, extra_args=None):
    if clusters_factory:
        actual_response = _create_cluster_with_warnings(clusters_factory, cluster_config, extra_args=extra_args)
    else:
        actual_response = cluster.update(
            cluster_config, extra_args=extra_args, wait=False, log_error=False, raise_on_error=False
        )
    expected_validation_errors = expected_response.get("configurationValidationErrors")
    if expected_validation_errors:
        # If validation error is expected. The code below checks for the validation error without enforcing the order
        # of errors and warnings and use Regex to match the error message
        actual_validation_errors = actual_response["configurationValidationErrors"]
        assert_that(actual_validation_errors).is_length(len(expected_validation_errors))
        for actual_error in actual_validation_errors:
            for expected_error in expected_validation_errors:
                if actual_error["type"] == expected_error["type"]:
                    # Either check the regex of expected_message match actual failure or check the
                    # whole strings are equal. This is to deal with strings having regex symbols (e.g. "[") inside
                    assert_that(
                        re.search(expected_error["message"], actual_error["message"])
                        or expected_error["message"] == actual_error["message"]
                    )
                    assert_that(actual_error["level"]).is_equal_to(expected_error["level"])
    else:
        # Otherwise, assert the actual response is exactly as expected
        assert_that(actual_response).is_equal_to(expected_response)


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


def _find_cluster_with_pagination(cmd_args, cluster_name):
    result = run_command(cmd_args)
    response = json.loads(result.stdout)
    found_cluster = _find_cluster_in_list(cluster_name, response["items"])
    while response.get("nextToken") and found_cluster is None:
        cmd_args_with_next_token = cmd_args + ["--next-token", response["nextToken"]]
        result = run_command(cmd_args_with_next_token)
        response = json.loads(result.stdout)
        found_cluster = _find_cluster_in_list(cluster_name, response["items"])
    return found_cluster


def _find_cluster_in_list(cluster_name, cluster_list):
    for cluster in cluster_list:
        if cluster_name == cluster["clusterName"]:
            return cluster


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
    cluster.stop()
    cluster.stop()
    cluster.start()
    compute_fleet = cluster.describe_compute_fleet()
    last_start_time = compute_fleet["lastStatusUpdatedTime"]
    logging.info("Checking last status update time is updated")
    assert_that(last_stop_time < last_start_time)
    wait_for_num_instances_in_cluster(cluster.cfn_name, cluster.region, desired=expected_num_nodes)
    _test_describe_instances(cluster)
    check_status(cluster, "CREATE_COMPLETE", "running", "RUNNING")


def _test_pcluster_export_cluster_logs(s3_bucket_factory, cluster):
    """Test pcluster export-cluster-logs functionality."""
    instance_ids = cluster.get_cluster_instance_ids()

    logging.info("Testing that pcluster export-cluster-logs is working as expected")
    bucket_name = s3_bucket_factory()
    logging.info("bucket is %s", bucket_name)

    # set bucket permissions
    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Action": "s3:GetBucketAcl",
                "Effect": "Allow",
                "Resource": f"arn:aws:s3:::{bucket_name}",
                "Principal": {"Service": f"logs.{cluster.region}.amazonaws.com"},
            },
            {
                "Action": "s3:PutObject",
                "Effect": "Allow",
                "Resource": f"arn:aws:s3:::{bucket_name}/*",
                "Condition": {"StringEquals": {"s3:x-amz-acl": "bucket-owner-full-control"}},
                "Principal": {"Service": f"logs.{cluster.region}.amazonaws.com"},
            },
        ],
    }
    boto3.client("s3").put_bucket_policy(Bucket=bucket_name, Policy=json.dumps(bucket_policy))

    with tempfile.TemporaryDirectory() as tempdir:
        # export archive
        output_file = f"{tempdir}/testfile.tar.gz"
        bucket_prefix = "test_prefix"
        cluster.export_logs(bucket=bucket_name, output=output_file, bucket_prefix=bucket_prefix)

        # check archive prefix and content
        with tarfile.open(output_file) as archive:

            # check the cfn stack events file is present
            stack_events_file_found = False
            for file in archive:
                if f"{cluster.name}-cfn-events" in file.name:
                    stack_events_file_found = True
                    break
            assert_that(stack_events_file_found).is_true()

            # check there are the logs of all the instances
            for instance_id in set(instance_ids):
                instance_found = False
                for file in archive:
                    if instance_id in file.name:
                        instance_found = True
                        break
                assert_that(instance_found).is_true()

    # check bucket_prefix folder has been removed from S3
    bucket_cleaned_up = False
    try:
        boto3.resource("s3").Object(bucket_name, bucket_prefix).load()
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            bucket_cleaned_up = True
    assert_that(bucket_cleaned_up).is_true()


def _test_pcluster_list_cluster_log_streams(cluster):
    """Test pcluster list-cluster-logs functionality and return cfn-init log stream name."""
    logging.info("Testing that pcluster list-cluster-log-streams is working as expected")
    list_streams_result = cluster.list_log_streams()
    streams = list_streams_result["items"]

    stream_names = {stream["logStreamName"] for stream in streams}
    expected_log_streams = {"cfn-init"}

    # check there are the logs of all the instances
    for instance in cluster.describe_cluster_instances():
        for stream_name in expected_log_streams:
            assert_that(stream_names).contains(instance_stream_name(instance, stream_name))


def _test_pcluster_get_cluster_log_events(cluster):
    """Test pcluster get-cluster-log-events functionality."""
    logging.info("Testing that pcluster get-cluster-log-events is working as expected")
    cluster_info = cluster.describe_cluster()
    cfn_init_log_stream = instance_stream_name(cluster_info["headnode"], "cfn-init")
    cloud_init_debug_msg = "[DEBUG] CloudFormation client initialized with endpoint"

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
            assert_that(events[0]["message"]).contains(cloud_init_debug_msg)

        if expect_first is False:
            assert_that(events[0]["message"]).does_not_contain(cloud_init_debug_msg)


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
