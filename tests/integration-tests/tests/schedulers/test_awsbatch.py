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
from tests.common.schedulers_common import AWSBatchCommands


@pytest.mark.batch_dockerfile_deps
@pytest.mark.skip_regions(["ap-northeast-3", "us-gov-east-1", "us-gov-west-1"])
@pytest.mark.instances(["c5.xlarge", "t2.large", "m6g.xlarge"])
@pytest.mark.dimensions("*", "*", "alinux", "awsbatch")
@pytest.mark.dimensions("*", "*", "alinux2", "awsbatch")
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
    awsbatch_commands = AWSBatchCommands(remote_command_executor)
    result = remote_command_executor.run_remote_command("awsbsub --vcpus 2 --memory 256 --timeout 60 sleep 300")
    job_id = awsbatch_commands.assert_job_submitted(result.stdout)

    remote_command_executor.run_remote_command("awsbkill {0}".format(job_id))
    status = awsbatch_commands.wait_job_completed(job_id)

    assert_that(status).contains_only("FAILED")
    result = remote_command_executor.run_remote_command("awsbstat -d {0}".format(job_id))
    assert_that(result.stdout).matches(r"statusReason\s+: Terminated by the user")


def _test_job_submission(remote_command_executor, submit_command, additional_files=None, children_number=0):
    logging.debug("Submitting Batch job")
    awsbatch_commands = AWSBatchCommands(remote_command_executor)
    result = remote_command_executor.run_remote_command(submit_command, additional_files=additional_files)
    job_id = awsbatch_commands.assert_job_submitted(result.stdout)
    logging.debug("Submitted Batch job id: {0}".format(job_id))
    awsbatch_commands.wait_job_completed(job_id)
    try:
        awsbatch_commands.assert_job_succeeded(job_id, children_number)
    except AssertionError:
        remote_command_executor.run_remote_command(f"awsbout {job_id}", raise_on_error=False, log_output=True)
        raise
