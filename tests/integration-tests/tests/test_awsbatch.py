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
@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
def test_awsbatch(pcluster_config_reader, clusters_factory, test_datadir):
    """
    Test all AWS Batch related features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    _test_simple_job_submission(remote_command_executor, test_datadir)
    _test_array_submission(remote_command_executor)
    _test_mnp_submission(remote_command_executor, test_datadir)
    _test_job_kill(remote_command_executor)


def _test_simple_job_submission(remote_command_executor, test_datadir):
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


def _test_array_submission(remote_command_executor):
    logging.info("Testing array submission.")
    _test_job_submission(remote_command_executor, "awsbsub --vcpus 1 --memory 128 -a 4 sleep 1", children_number=4)


def _test_mnp_submission(remote_command_executor, test_datadir):
    logging.info("Testing MNP submission with MPI job.")
    _test_job_submission(
        remote_command_executor,
        "awsbsub --vcpus 1 --memory 128 -n 4 -cf test_mpi_job.sh",
        additional_files=[str(test_datadir / "test_mpi_job.sh")],
        children_number=4,
    )


def _test_job_kill(remote_command_executor):
    logging.info("Testing job kill.")
    result = remote_command_executor.run_remote_command("awsbsub --vcpus 2 --memory 256 --timeout 60 sleep 300")
    job_id = _assert_job_submitted(result.stdout)

    remote_command_executor.run_remote_command("awsbkill {0}".format(job_id))
    status = _wait_job_completed(remote_command_executor, job_id)

    assert_that(status).contains_only("FAILED")
    result = remote_command_executor.run_remote_command("awsbstat -d {0}".format(job_id))
    assert_that(result.stdout).matches(r"statusReason\s+: Terminated by the user")


def _test_job_submission(remote_command_executor, submit_command, additional_files=None, children_number=0):
    logging.debug("Submitting Batch job")
    result = remote_command_executor.run_remote_command(submit_command, additional_files=additional_files)
    job_id = _assert_job_submitted(result.stdout)
    logging.debug("Submitted Batch job id: {0}".format(job_id))
    status = _wait_job_completed(remote_command_executor, job_id)
    assert_that(status).is_length(1 + children_number)
    assert_that(status).contains_only("SUCCEEDED")


def _assert_job_submitted(awsbsub_output):
    __tracebackhide__ = True
    match = re.match(r"Job ([a-z0-9\-]{36}) \(.+\) has been submitted.", awsbsub_output)
    assert_that(match).is_not_none()
    return match.group(1)


@retry(
    retry_on_result=lambda result: "FAILED" not in result and any(status != "SUCCEEDED" for status in result),
    wait_fixed=seconds(7),
    stop_max_delay=minutes(15),
)
def _wait_job_completed(remote_command_executor, job_id):
    result = remote_command_executor.run_remote_command("awsbstat -d {0}".format(job_id))
    return re.findall(r"status\s+: (.+)", result.stdout)
