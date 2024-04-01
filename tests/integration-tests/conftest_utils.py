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
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

import pluggy
import pytest
import yaml
from conftest_markers import DIMENSIONS_MARKER_ARGS
from filelock import FileLock
from framework.metrics_publisher import Metric, MetricsPublisher
from time_utils import microseconds
from utils import dict_add_nested_key, dict_has_nested_key


def add_properties_to_report(item: pytest.Item):
    props = []

    # Add properties for test dimensions, obtained from fixtures passed to tests
    for dimension in DIMENSIONS_MARKER_ARGS:
        value = item.funcargs.get(dimension)
        if value:
            props.append((dimension, value))

    # Add property for feature tested, obtained from filename containing the test
    props.append(("feature", extract_tested_component_from_filename(item)))

    for dimension_value_pair in props:
        if dimension_value_pair not in item.user_properties:
            item.user_properties.append(dimension_value_pair)


def update_failed_tests_config(item: pytest.Item):
    out_dir = Path(item.config.getoption("output_dir"))
    if not str(out_dir).endswith(".out"):
        # Navigate to the parent dir in case of parallel run so that we can access the shared parent dir
        out_dir = out_dir.parent

    out_file = out_dir / "failed_tests_config.yaml"
    logging.info("Updating failed tests config file %s", out_file)
    # We need to acquire a lock first to prevent concurrent edits to this file
    with FileLock(str(out_file) + ".lock"):
        failed_tests = {"test-suites": {}}
        if out_file.is_file():
            with open(str(out_file), encoding="utf-8") as f:
                failed_tests = yaml.safe_load(f)

        # item.node.nodeid example:
        # 'dcv/test_dcv.py::test_dcv_configuration[eu-west-1-c5.xlarge-centos7-slurm-8443-0.0.0.0/0-/shared]'
        feature, test_id = item.nodeid.split("/", 1)
        test_id = test_id.split("[", 1)[0]
        dimensions = {}
        for dimension in DIMENSIONS_MARKER_ARGS:
            value = item.callspec.params.get(dimension)
            if value:
                dimensions[dimension + "s"] = [value]

        if not dict_has_nested_key(failed_tests, ("test-suites", feature, test_id)):
            dict_add_nested_key(failed_tests, [], ("test-suites", feature, test_id, "dimensions"))
        if dimensions not in failed_tests["test-suites"][feature][test_id]["dimensions"]:
            failed_tests["test-suites"][feature][test_id]["dimensions"].append(dimensions)
            with open(out_file, "w", encoding="utf-8") as f:
                yaml.dump(failed_tests, f)


def extract_tested_component_from_filename(item: pytest.Item):
    """Extract portion of test item's filename identifying the component it tests."""
    test_location = os.path.splitext(os.path.basename(item.location[0]))[0]
    return re.sub(r"test_|_test", "", test_location)


def add_filename_markers(items: List[pytest.Item], config: pytest.Config):
    """Add a marker based on the name of the file where the test case is defined."""
    for item in items:
        marker = extract_tested_component_from_filename(item)
        # This dynamically registers markers in pytest so that warning for the usage of undefined markers are not
        # displayed
        config.addinivalue_line("markers", marker)
        item.add_marker(marker)


def runtest_hook_start_end_time(item: pytest.Item, when: str):
    """Generator function to store start and end times for test phases."""
    logging.info(f"Starting {when} for test {item.name}")
    item.user_properties.append((f"start_time_{when}", datetime.timestamp(datetime.now(timezone.utc))))
    # execute all other hooks to obtain the call object
    outcome: pluggy.Result = yield
    item.user_properties.append((f"end_time_{when}", datetime.timestamp(datetime.now(timezone.utc))))
    call_list: List[pytest.CallInfo] = outcome.get_result()
    logging.info(f"{when} list {call_list}")


def publish_test_metrics(when: str, item: pytest.Item, rep: pytest.TestReport):
    """
    Publish test metrics specific to a given test execution.

    Dimensions - feature, test name, region, os, instance type
    Execution times - for each phase and total
    Test Result - Pass/Fail
    """
    pub = MetricsPublisher(get_user_prop(item, "region"))
    dimensions = [
        {"Name": dimension, "Value": get_user_prop(item, dimension)}
        for dimension in ["feature", "os", "instance", "region"]
    ]
    dimensions.append({"Name": "test_name", "Value": item.location[2]})
    # Create a list of metrics
    metrics = create_phase_metrics(when, item, rep, dimensions)
    pub.publish_metrics_to_cloudwatch("ParallelCluster/IntegrationTests", metrics)


def get_user_prop(item: pytest.Item, prop: str) -> Any:
    """From a list of tuples, get the desired user property."""
    for user_prop in item.user_properties:
        if user_prop[0] == prop:
            return user_prop[1]


def create_phase_metrics(when: str, item: pytest.Item, rep: pytest.TestReport, dimensions: List[dict[str, str]]):
    metrics = [
        Metric(f"{when}_result", int(rep.passed), "None", dimensions),
        Metric(
            f"{when}_time",
            int(microseconds(get_user_prop(item, f"end_time_{when}") - get_user_prop(item, f"start_time_{when}"))),
            "Microseconds",
            dimensions,
        ),
    ]
    if when == "teardown":
        metrics.append(
            Metric(
                "total_time",
                int(microseconds(get_user_prop(item, "end_time_teardown") - get_user_prop(item, "start_time_setup"))),
                "Microseconds",
                dimensions,
            )
        )
    return metrics
