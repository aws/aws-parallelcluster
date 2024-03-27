# Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from typing import Optional, Tuple

import pluggy
import pytest
from _pytest._code import ExceptionInfo
from conftest_utils import (
    add_properties_to_report,
    publish_test_metrics,
    runtest_hook_start_end_time,
    update_failed_tests_config,
)
from utils import SetupError, set_logger_formatter

# This file has a special meaning for pytest. See https://docs.pytest.org/en/2.7.3/plugins.html for
# additional details.


def pytest_runtest_logstart(nodeid: str, location: Tuple[str, Optional[int], str]):
    """Called to execute the test item."""
    test_name = location[2]
    set_logger_formatter(
        logging.Formatter(fmt=f"%(asctime)s - %(levelname)s - %(process)d - {test_name} - %(module)s - %(message)s")
    )
    logging.info("Running test %s", test_name)


def pytest_runtest_logfinish(nodeid: str, location: Tuple[str, Optional[int], str]):
    logging.info("Completed test %s", location[2])
    set_logger_formatter(logging.Formatter(fmt="%(asctime)s - %(levelname)s - %(process)d - %(module)s - %(message)s"))


def pytest_runtest_logreport(report: pytest.TestReport):
    logging.info(f"Starting log report for test {report.nodeid}")
    # Set the approximate start time for the test
    logging.info(f"Report keys {list(report.keywords)}")
    logging.info(f"Report props {list(report.user_properties)}")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_setup(item: pytest.Item):
    yield from runtest_hook_start_end_time(item, "setup")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_call(item: pytest.Item):
    yield from runtest_hook_start_end_time(item, "call")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item):
    yield from runtest_hook_start_end_time(item, "teardown")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    """Making test result information available in fixtures"""
    # add dimension properties to report
    add_properties_to_report(item)

    # execute all other hooks to obtain the report object
    outcome: pluggy.Result = yield
    rep: pytest.TestReport = outcome.get_result()
    logging.info(f"rep {rep}")
    # set a report attribute for each phase of a call, which can
    # be "setup", "call", "teardown"
    setattr(item, "rep_" + rep.when, rep)

    if rep.when in ["setup", "call"] and rep.failed:
        exception_info: ExceptionInfo = call.excinfo
        if exception_info.value and isinstance(exception_info.value, SetupError):
            rep.when = "setup"
        try:
            update_failed_tests_config(item)
        except Exception as e:
            logging.error("Failed when generating config for failed tests: %s", e, exc_info=True)
    # Set the approximate start time for the test
    logging.info(f"Report keys {list(item.keywords)}")
    try:
        publish_test_metrics(rep.when, item, rep)
    except Exception as exc:
        logging.info(f"There was a {type(exc)} error with {exc} publishing the report!")
