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
import re

import pytest
from retrying import retry

from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from time_utils import minutes, seconds


@pytest.mark.regions(["us-east-1", "eu-west-1", "cn-north-1", "us-gov-west-1"])
@pytest.mark.instances(["c5.xlarge", "t2.large"])
@pytest.mark.dimensions("*", "*", "alinux", "awsbatch")
def test_simple_job_submission(region, os, instance, scheduler, pcluster_config_reader, clusters_factory, test_datadir):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    logging.info("Testing inline submission.")
    _test_job_submission(remote_command_executor, "awsbsub --vcpus 2 --memory 256 --timeout 60 sleep 1")

    # FIXME: uncomment once this bug is fixed
    # logging.info("Testing inline submission with env.")
    # _test_job_submission(
    #     remote_command_executor,
    #     'export TEST=test && awsbsub --vcpus 2 --memory 256 --timeout 60 -e TEST "env | grep TEST=test"',
    # )

    logging.info("Testing stdin submission with env")
    _test_job_submission(
        remote_command_executor,
        'export TEST=test && echo "env | grep TEST=test" | awsbsub --vcpus 2 --memory 256 --timeout 60 -e TEST',
    )

    logging.info("Testing command file with env")
    _test_job_submission(
        remote_command_executor,
        "export TEST=test && awsbsub --vcpus 2 --memory 256 --timeout 60 -e TEST -cf test_simple_job.sh",
        [str(test_datadir / "test_simple_job.sh")],
    )


def _test_job_submission(remote_command_executor, submit_command, additional_files=None):
    logging.debug("Submitting Batch job")
    result = remote_command_executor.run_remote_command(submit_command, additional_files=additional_files)
    job_id = _assert_job_submitted(result.stdout)
    logging.debug("Submitted Batch job id: {0}".format(job_id))
    status = _wait_job_completed(remote_command_executor, job_id)
    assert_that(status).is_equal_to("SUCCEEDED")


def _assert_job_submitted(awsbsub_output):
    __tracebackhide__ = True
    match = re.match(r"Job ([a-z0-9\-]{36}) \(.+\) has been submitted.", awsbsub_output)
    assert_that(match).is_not_none()
    return match.group(1)


@retry(
    retry_on_result=lambda result: result not in ["SUCCEEDED", "FAILED"],
    wait_fixed=seconds(10),
    stop_max_delay=minutes(3),
)
def _wait_job_completed(remote_command_executor, job_id):
    result = remote_command_executor.run_remote_command("awsbstat {0}".format(job_id))
    return re.search(r"status.+: (.+)", result.stdout).group(1)
