# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import xmltodict
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor

from tests.common.assertions import assert_no_errors_in_logs
from tests.common.utils import read_remote_file, run_system_analyzer, wait_process_completion

FABTESTS_BASIC_TESTS = ["rdm_tagged_bw", "rdm_tagged_pingpong"]

FABTESTS_GDRCOPY_TESTS = ["runt"]


@pytest.mark.usefixtures("serial_execution_by_instance")
def test_fabric(
    os,
    region,
    scheduler,
    instance,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    scheduler_commands_factory,
    request,
):
    """
    Test tha EFA is working according to Fabtests, that is the official libfabric test suite.
    See https://github.com/ofiwg/libfabric/tree/main/fabtests
    """

    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    run_system_analyzer(cluster, scheduler_commands_factory, request, partition="q1")

    fabtests_report = _execute_fabtests(remote_command_executor, test_datadir, instance)

    num_tests = int(fabtests_report.get("testsuites", {}).get("testsuite", {}).get("@tests", None))
    num_failures = int(fabtests_report.get("testsuites", {}).get("testsuite", {}).get("@failures", None))

    assert_that(num_tests, description="Cannot read number of tests from Fabtests report").is_not_none()
    assert_that(num_failures, description="Cannot read number of failures from Fabtests report").is_not_none()

    if num_failures > 0:
        logging.info(f"Fabtests report:\n{fabtests_report}")

    assert_that(num_failures, description=f"{num_failures}/{num_tests} libfabric tests are failing").is_equal_to(0)
    assert_no_errors_in_logs(remote_command_executor, scheduler)


def _execute_fabtests(remote_command_executor, test_datadir, instance):
    fabtests_dir = "/shared/fabtests"
    fabtests_pid_file = f"{fabtests_dir}/outputs/fabtests.pid"
    fabtests_log_file = f"{fabtests_dir}/outputs/fabtests.log"
    fabtests_report_file = f"{fabtests_dir}/outputs/fabtests.report"

    logging.info("Installing Fabtests")
    remote_command_executor.run_remote_script(
        str(test_datadir / "install-fabtests.sh"), args=[fabtests_dir], timeout=600
    )

    logging.info("Running Fabtests")
    test_cases = FABTESTS_BASIC_TESTS + FABTESTS_GDRCOPY_TESTS if instance == "p4d.24xlarge" else FABTESTS_BASIC_TESTS
    remote_command_executor.run_remote_script(
        str(test_datadir / "run-fabtests.sh"),
        args=[
            fabtests_dir,
            fabtests_pid_file,
            fabtests_log_file,
            fabtests_report_file,
            "q1-st-efa-enabled-1",
            "q1-st-efa-enabled-2",
            ",".join(test_cases),
            "enable-gdr" if instance == "p4d.24xlarge" else "skip-gdr",
        ],
        timeout=60,
        pty=False,
    )

    pid = read_remote_file(remote_command_executor, fabtests_pid_file)

    wait_process_completion(remote_command_executor, pid)

    logging.info("Retrieving Fabtests report")
    report_content = read_remote_file(remote_command_executor, fabtests_report_file)
    return xmltodict.parse(report_content)
