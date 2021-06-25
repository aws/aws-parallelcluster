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
import json
import logging
import tarfile
import tempfile

import boto3
import botocore
import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from utils import get_cluster_nodes_instance_ids

from tests.common.assertions import assert_no_errors_in_logs, wait_for_num_instances_in_cluster


@pytest.mark.regions(["us-east-2"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.oss(["ubuntu1804"])
@pytest.mark.usefixtures("region", "os", "instance")
def test_slurm_cli_commands(scheduler, region, pcluster_config_reader, clusters_factory, s3_bucket_factory):
    """Test pcluster cli commands are working."""
    # Use long scale down idle time so we know nodes are terminated by pcluster stop
    cluster_config = pcluster_config_reader(scaledown_idletime=60)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    instance_ids = _test_pcluster_instances_and_status(cluster, region, compute_fleet_status="RUNNING")
    _test_pcluster_stop_and_start(cluster, region, expected_num_nodes=2)
    _test_pcluster_export_cluster_logs(s3_bucket_factory, cluster, region, instance_ids)
    cfn_init_log_stream = _test_pcluster_list_cluster_logs(cluster, instance_ids)
    _test_pcluster_get_cluster_log_events(cluster, cfn_init_log_stream)
    assert_no_errors_in_logs(remote_command_executor, scheduler)


def _test_pcluster_instances_and_status(cluster, region, compute_fleet_status=None):
    """Test pcluster status and pcluster instances functionalities."""
    logging.info("Testing that pcluster status and pcluster instances output are expected")
    cluster_instances_from_ec2 = get_cluster_nodes_instance_ids(cluster.cfn_name, region)
    cluster_instances_from_cli = cluster.instances()
    assert_that(set(cluster_instances_from_cli)).is_equal_to(set(cluster_instances_from_ec2))
    expected_status_details = ["Status: CREATE_COMPLETE", "HeadNode: running"]
    if compute_fleet_status:
        expected_status_details.append("ComputeFleetStatus: {0}".format(compute_fleet_status))
    cluster_status = cluster.status()
    for detail in expected_status_details:
        assert_that(cluster_status).contains(detail)
    return cluster_instances_from_cli


def _test_pcluster_stop_and_start(cluster, region, expected_num_nodes):
    """Test pcluster start and stop functionality."""
    logging.info("Testing pcluster stop functionalities")
    cluster_stop_output = cluster.stop()
    # Sample pcluster stop output:
    # Compute fleet status is: RUNNING. Submitting status change request.
    # Request submitted successfully. It might take a while for the transition to complete.
    # Please run 'pcluster status' if you need to check compute fleet status
    expected_stop_output = (
        r"Compute fleet status is: RUNNING.*Submitting status change request.*" "\nRequest submitted successfully"
    )
    assert_that(cluster_stop_output).matches(expected_stop_output)
    wait_for_num_instances_in_cluster(cluster.cfn_name, region, desired=0)
    _test_pcluster_instances_and_status(cluster, region, compute_fleet_status="STOPPED")

    logging.info("Testing pcluster start functionalities")
    # Do a complicated sequence of start and stop and see if commands will still work
    cluster.start()
    cluster.stop()
    cluster.stop()
    cluster_start_output = cluster.start()
    # Sample pcluster start output:
    # Compute fleet status is: STOPPED. Submitting status change request.
    # Request submitted successfully. It might take a while for the transition to complete.
    # Please run 'pcluster status' if you need to check compute fleet status
    expected_start_output = (
        r"Compute fleet status is: STOP.*Submitting status change request.*" "\nRequest submitted successfully"
    )
    assert_that(cluster_start_output).matches(expected_start_output)
    wait_for_num_instances_in_cluster(cluster.cfn_name, region, desired=expected_num_nodes)
    _test_pcluster_instances_and_status(cluster, region, compute_fleet_status="RUNNING")


def _test_pcluster_export_cluster_logs(s3_bucket_factory, cluster, region, instance_ids):
    """Test pcluster export-cluster-logs functionality."""
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
                "Principal": {"Service": f"logs.{region}.amazonaws.com"},
            },
            {
                "Action": "s3:PutObject",
                "Effect": "Allow",
                "Resource": f"arn:aws:s3:::{bucket_name}/*",
                "Condition": {"StringEquals": {"s3:x-amz-acl": "bucket-owner-full-control"}},
                "Principal": {"Service": f"logs.{region}.amazonaws.com"},
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


def _test_pcluster_list_cluster_logs(cluster, instance_ids):
    """Test pcluster list-cluster-logs functionality and return cfn-init log stream name."""
    logging.info("Testing that pcluster list-cluster-logs is working as expected")
    std_output = cluster.list_logs()

    # check cfn stack events headers and log stream name
    for item in ["Stack Events Stream", "Cluster Creation Time", "Last Update Time", f"{cluster.name}-cfn-events"]:
        assert_that(std_output).contains(item)

    # check CW log streams headers
    for item in ["Log Stream Name", "First Event", "Last Event"]:
        assert_that(std_output).contains(item)

    # check there are the logs of all the instances
    for instance_id in set(instance_ids):
        assert_that(std_output).contains(instance_id)

    # search for cfn-init log stream name
    cfn_init_log_stream = None
    for line in std_output.split("\n"):
        if "cfn-init" in line:
            cfn_init_log_stream = line.split(" ")[0]
            break
    return cfn_init_log_stream


def _test_pcluster_get_cluster_log_events(cluster, cfn_init_log_stream):
    """Test pcluster get-cluster-log-events functionality."""
    logging.info("Testing that pcluster get-cluster-log-events is working as expected")
    # Check cfn-init log stream
    std_output = cluster.get_log_events(cfn_init_log_stream, head=10)
    assert_that(std_output).contains("[DEBUG] CloudFormation client initialized with endpoint")

    # Check CFN Stack events stream with tail option
    std_output = cluster.get_log_events(f"{cluster.name}-cfn-events", tail=10)
    assert_that(std_output).contains(f"CREATE_COMPLETE AWS::CloudFormation::Stack {cluster.name}")

    # Check CFN Stack events stream with head option
    std_output = cluster.get_log_events(f"{cluster.name}-cfn-events", head=10)
    assert_that(std_output).contains(f"CREATE_IN_PROGRESS AWS::CloudFormation::Stack {cluster.name} User Initiated")
