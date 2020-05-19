# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import logging

import pytest

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from tests.common.assertions import assert_no_errors_in_logs


@pytest.mark.regions(["us-east-1"])
@pytest.mark.schedulers(["sge", "awsbatch"])
@pytest.mark.skip_instances(["g3.8xlarge"])
@pytest.mark.oss(["alinux2"])
@pytest.mark.usefixtures("os")
def test_iam_policies(region, scheduler, pcluster_config_reader, clusters_factory):
    """Test IAM Policies"""
    cluster_config = pcluster_config_reader(
        iam_policies="arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess, arn:aws:iam::aws:policy/AWSBatchFullAccess"
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _test_s3_access(remote_command_executor, region)
    _test_batch_access(remote_command_executor, region)

    if not scheduler == "awsbatch":
        assert_no_errors_in_logs(remote_command_executor, ["/var/log/sqswatcher", "/var/log/jobwatcher"])


def _test_s3_access(remote_command_executor, region):
    logging.info("Testing S3 Access")
    result = remote_command_executor.run_remote_command("AWS_DEFAULT_REGION={0} aws s3 ls".format(region)).stdout
    # An error occurred (AccessDenied) when calling the ListBuckets operation: Access Denied
    assert_that(result).does_not_contain("AccessDenied")


def _test_batch_access(remote_command_executor, region):
    logging.info("Testing AWS Batch Access")
    result = remote_command_executor.run_remote_command(
        "AWS_DEFAULT_REGION={0} aws batch describe-compute-environments".format(region)
    ).stdout
    # An error occurred (AccessDeniedException) when calling the DescribeComputeEnvironments operation: ...
    assert_that(result).does_not_contain("AccessDeniedException")
