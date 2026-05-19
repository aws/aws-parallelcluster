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
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

import boto3
import jsonpickle
import pluggy
import pytest
import yaml
from conftest_markers import DIMENSIONS_MARKER_ARGS
from filelock import FileLock
from framework.framework_constants import METADATA_TABLE
from framework.metadata_table_manager import MetadataTableManager, PhaseMetadata, TestMetadata
from framework.metrics_publisher import Metric, MetricsPublisher
from time_utils import microseconds
from utils import (
    DEFAULT_PARTITION,
    DEFAULT_REPORTING_REGION,
    PARTITION_MAP,
    REPORTING_REGION_MAP,
    dict_add_nested_key,
    dict_has_nested_key,
)


def add_properties_to_report(item: pytest.Item):
    props = []

    # Add properties for test dimensions, obtained from fixtures passed to tests
    # Try funcargs first, fall back to callspec.params (needed for @pytest.mark.usefixtures)
    for dimension in DIMENSIONS_MARKER_ARGS:
        value = item.funcargs.get(dimension)
        if value and dimension == "region":
            logging.info(f"region={value} (from funcargs) for {item.nodeid}")
        if not value and hasattr(item, "callspec"):
            value = item.callspec.params.get(dimension)
            if value and dimension == "region":
                logging.info(f"region={value} (from callspec.params) for {item.nodeid}")
        if value:
            props.append((dimension, value))
        elif dimension == "region":
            logging.warning(f"region=None for {item.nodeid}")

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


def publish_test_metrics(item: pytest.Item, rep: pytest.TestReport):
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
    metrics = create_phase_metrics(item, rep, dimensions)
    pub.publish_metrics_to_cloudwatch("ParallelCluster/IntegrationTests", metrics)


def get_user_prop(item: pytest.Item, prop: str) -> Any:
    """From a list of tuples, get the desired user property."""
    for user_prop in item.user_properties:
        if user_prop[0] == prop:
            return user_prop[1]


def update_user_prop(item: pytest.Item, prop: str, new_data: Any) -> Any:
    """From a list of tuples, get the desired user property and update it"""
    for index, user_prop in enumerate(item.user_properties):
        if user_prop[0] == prop:
            item.user_properties[index] = (prop, new_data)
            return item.user_properties[index][1]


def create_phase_metrics(item: pytest.Item, rep: pytest.TestReport, dimensions: List[dict[str, str]]):
    metrics = [
        Metric(f"{rep.when}_result", int(rep.passed), "None", dimensions),
        Metric(
            f"{rep.when}_time",
            int(
                microseconds(
                    get_user_prop(item, f"end_time_{rep.when}") - get_user_prop(item, f"start_time_{rep.when}")
                )
            ),
            "Microseconds",
            dimensions,
        ),
    ]
    if rep.when == "teardown":
        metrics.append(
            Metric(
                "total_time",
                int(microseconds(get_user_prop(item, "end_time_teardown") - get_user_prop(item, "start_time_setup"))),
                "Microseconds",
                dimensions,
            )
        )
    return metrics


def publish_test_metadata(item: pytest.Item, rep: pytest.TestReport):
    """Publish test metadata to the metadata table."""
    reporting_region = get_reporting_region(get_user_prop(item, "region"))
    metadata_table_mgr = MetadataTableManager(reporting_region, METADATA_TABLE)
    logging.info(f"Publishing test metadata: item {item} rep {rep} to {METADATA_TABLE} in {reporting_region}")
    test_metadata = None
    if rep.when == "setup":
        # Initialize the test data
        test_metadata = TestMetadata(
            item.location[2],
            region=get_user_prop(item, "region"),
            os=get_user_prop(item, "os"),
            feature=get_user_prop(item, "feature"),
            instance_type=get_user_prop(item, "instance"),
            global_build_number=item.config.getoption("--global-build-number"),
            cli_commit=item.config.getoption("--pcluster-git-ref"),
            cookbook_commit=item.config.getoption("--cookbook-git-ref"),
            node_commit=item.config.getoption("--node-git-ref"),
            cluster_stack_name="none",
            cw_log_group_name="none",
            setup_metadata=PhaseMetadata(
                rep.when,
                status=rep.outcome,
                start_time=get_user_prop(item, f"start_time_{rep.when}"),
                end_time=get_user_prop(item, f"end_time_{rep.when}"),
            ),
        )
    if rep.when == "call":
        # Update the call test data
        test_metadata = jsonpickle.decode(get_user_prop(item, "metadata"))
        test_metadata.call_metadata = PhaseMetadata(
            rep.when,
            status=rep.outcome,
            start_time=get_user_prop(item, f"start_time_{rep.when}"),
            end_time=get_user_prop(item, f"end_time_{rep.when}"),
        )
        test_metadata.cluster_stack_name = get_user_prop(item, "cluster_stack_name")
        test_metadata.cw_log_group_name = get_user_prop(item, "cw_log_group_name")
        test_metadata.cluster_creation_time = get_user_prop(item, "cluster_creation_time")
    if rep.when == "teardown":
        # Update the teardown test data
        test_metadata = jsonpickle.decode(get_user_prop(item, "metadata"))
        test_metadata.teardown_metadata = PhaseMetadata(
            rep.when,
            status=rep.outcome,
            start_time=get_user_prop(item, f"start_time_{rep.when}"),
            end_time=get_user_prop(item, f"end_time_{rep.when}"),
        )
        max_launch_time, min_launch_time, average_launch_time = _collect_compute_node_launch_time(
            test_metadata.cw_log_group_name, test_metadata.region
        )
        test_metadata.compute_max_launch_time = max_launch_time
        test_metadata.compute_min_launch_time = min_launch_time
        test_metadata.compute_average_launch_time = average_launch_time
    # This prop needs to be serialized before saving to the user_props
    if update_user_prop(item, "metadata", jsonpickle.encode(test_metadata)):
        logging.info(f"Updated the metadata during the {rep.when} phase: {get_user_prop(item, 'metadata')}")
    else:
        item.user_properties.append(("metadata", jsonpickle.encode(test_metadata)))
        logging.info(f"Added the metadata during the {rep.when} phase: {get_user_prop(item, 'metadata')}")
    execution_count = getattr(item, "execution_count", 1)
    if execution_count > 1:
        test_metadata.id = f"{test_metadata.id}rerun{item.execution_count}"
    metadata_table_mgr.publish_metadata([test_metadata])


def _collect_compute_node_launch_time(log_group_name, region):
    # The compute node launch time is the period from
    # head node launches the compute node to the end of the cloud-init log in compute node
    if log_group_name is None:
        return 0, 0, 0
    logging.info("collect compute node launch time in %s", log_group_name)
    cloudwatch_client = boto3.client("logs", region_name=region)
    next_token = None
    instance_launch_logs = []
    launch_finish_time_by_instance = {}
    head_node_id = None
    while True:
        if next_token:
            response = cloudwatch_client.describe_log_streams(logGroupName=log_group_name, nextToken=next_token)
        else:
            response = cloudwatch_client.describe_log_streams(logGroupName=log_group_name)
        for log_stream in response["logStreams"]:
            # Example logstream name: ip-192-168-12-123.i-0b880471c42123123.clustermgtd
            log_stream_name = log_stream["logStreamName"].split(".")
            if "slurmd" == log_stream_name[2]:
                launch_finish_time_by_instance[log_stream_name[1]] = log_stream["firstEventTimestamp"]
            if log_stream_name[2] in ["clustermgtd", "slurm_resume"]:
                head_node_id = log_stream_name[1]
                _gather_instance_launch_logs(cloudwatch_client, instance_launch_logs, log_group_name, log_stream)
        next_token = response.get("nextToken")
        if next_token is None:
            break
    return _calculate_compute_launch_time(head_node_id, instance_launch_logs, launch_finish_time_by_instance)


def _calculate_compute_launch_time(head_node_id, instance_launch_logs, launch_finish_time_by_instance):
    max_launch_time = 0
    min_launch_time = 0
    total_launch_time = 0
    instance_num = 0
    for instance_id, launch_finish_time in launch_finish_time_by_instance.items():
        if instance_id == head_node_id:
            continue
        launch_start_time = _get_launch_time(instance_launch_logs, instance_id)
        if launch_start_time:
            instance_num += 1
            launch_time = launch_finish_time - launch_start_time
            total_launch_time += launch_time
            max_launch_time = max(max_launch_time, launch_time)
            if min_launch_time == 0:
                min_launch_time = launch_time
            else:
                min_launch_time = min(min_launch_time, launch_time)
    if instance_num > 0:
        return max_launch_time, min_launch_time, total_launch_time / instance_num
    else:
        return 0, 0, 0


def _get_log_stream_events(cloudwatch_client, log_group_name, log_stream):
    events = []
    event_next_token = None
    while True:
        if event_next_token:
            response = cloudwatch_client.get_log_events(
                logGroupName=log_group_name,
                logStreamName=log_stream["logStreamName"],
                nextToken=event_next_token,
            )
        else:
            response = cloudwatch_client.get_log_events(
                logGroupName=log_group_name, logStreamName=log_stream["logStreamName"], startFromHead=True
            )
        # Process and write events
        for event in response["events"]:
            events.append(event)

        # Check if there are more logs to fetch
        if event_next_token == response["nextForwardToken"]:
            break
        else:
            event_next_token = response["nextForwardToken"]
    return events


def _gather_instance_launch_logs(cloudwatch_client, instance_launch_logs, log_group_name, log_stream):
    events = _get_log_stream_events(cloudwatch_client, log_group_name, log_stream)
    for event in events:
        if "Nodes are now configured with instance" in event["message"]:
            instance_launch_logs.append(event)


def _get_launch_time(logs, instance_id):
    for log in logs:
        if instance_id in log["message"]:
            return log["timestamp"]


def get_reporting_region(region: str):
    """Get partition for the given region. If region is None, fall back to DEFAULT_REPORTING_REGION."""
    if not region:
        logging.warning("Region is None in get_reporting_region, falling back to default reporting region")
        return DEFAULT_REPORTING_REGION
    curr_partition = next(
        (partition for region_prefix, partition in PARTITION_MAP.items() if region.startswith(region_prefix)),
        DEFAULT_PARTITION,
    )
    return next(
        (region for partition, region in REPORTING_REGION_MAP.items() if partition == curr_partition),
        DEFAULT_REPORTING_REGION,
    )


def _any_test_failed_in_session(request):
    """Return True if any test in the session has recorded a failure (used for scope>function fixtures)."""
    return bool(getattr(request.session, "_pcluster_failed_tests", None))


def _current_test_failed(request):
    """Return True if the current test item has failed during setup or call phases."""
    for phase in ("setup", "call"):
        rep = getattr(request.node, f"rep_{phase}", None)
        if rep is not None and rep.failed:
            return True
    return False


def _get_retain_counter_path(request):
    """Return the path to the shared file used to track retained test failures across xdist workers.

    The file is placed in the parent of output_dir to ensure it is shared across regions,
    since each region gets its own output_dir subdirectory.
    """
    output_dir = request.config.getoption("output_dir", default=tempfile.gettempdir())
    # output_dir is typically <base>/OUT_DIR/<region>; go up to the base so all regions share the file
    parent_dir = os.path.dirname(output_dir) if output_dir else tempfile.gettempdir()
    return os.path.join(parent_dir, ".retain_on_failure_tests")


def _get_retained_stacks_path(request):
    """Return the path to the file listing stack names that should not be deleted by cleanup."""
    output_dir = request.config.getoption("output_dir", default=tempfile.gettempdir())
    parent_dir = os.path.dirname(output_dir) if output_dir else tempfile.gettempdir()
    return os.path.join(parent_dir, ".retained_stacks")


def register_retained_stack(request, stack_arn):
    """Register a stack ARN as retained so the Jenkins cleanup script skips it."""
    stacks_path = _get_retained_stacks_path(request)
    lock_path = stacks_path + ".lock"

    with FileLock(lock_path):
        if os.path.exists(stacks_path):
            with open(stacks_path, "r") as f:
                retained_stacks = set(line.strip() for line in f if line.strip())
        else:
            retained_stacks = set()

        retained_stacks.add(stack_arn)
        with open(stacks_path, "w") as f:
            f.write("\n".join(retained_stacks) + "\n")

    logging.info("Registered stack %s for retention", stack_arn)


def _record_test_id_for_retention(request, test_id):
    """Check if this test is already registered for retention, or register it if within the limit.

    Uses a file lock to coordinate across xdist workers.
    Returns (recorded, current_count, max_retain).
    """
    max_retain = request.config.getoption("retain_on_failure")
    counter_path = _get_retain_counter_path(request)
    lock_path = counter_path + ".lock"

    with FileLock(lock_path):
        if os.path.exists(counter_path):
            with open(counter_path, "r") as f:
                retained_tests = set(line.strip() for line in f if line.strip())
        else:
            retained_tests = set()

        # Already registered — allow retention without incrementing
        if test_id in retained_tests:
            return True, len(retained_tests), max_retain

        # Limit reached — deny
        if len(retained_tests) >= max_retain:
            return False, len(retained_tests), max_retain

        # Register this test
        retained_tests.add(test_id)
        with open(counter_path, "w") as f:
            f.write("\n".join(retained_tests) + "\n")

        return True, len(retained_tests), max_retain


def is_stack_retained(request, stack_arn):
    """Check if a specific stack ARN is registered in the retained stacks file."""
    stacks_path = _get_retained_stacks_path(request)
    lock_path = stacks_path + ".lock"

    with FileLock(lock_path):
        if os.path.exists(stacks_path):
            with open(stacks_path, "r") as f:
                retained_stacks = set(line.strip() for line in f if line.strip())
            return stack_arn in retained_stacks
    return False


def is_region_retained(request, region):
    """Check if any retained stack belongs to the given region.

    Stack ARNs contain the region: arn:aws:cloudformation:<region>:<account>:stack/...
    """
    stacks_path = _get_retained_stacks_path(request)
    lock_path = stacks_path + ".lock"

    with FileLock(lock_path):
        if os.path.exists(stacks_path):
            with open(stacks_path, "r") as f:
                retained_stacks = set(line.strip() for line in f if line.strip())
            for arn in retained_stacks:
                # ARN format: arn:aws:cloudformation:<region>:<account>:stack/<name>/<id>
                parts = arn.split(":")
                if len(parts) >= 4 and parts[3] == region:
                    return True
    return False


def retain_resources_on_teardown(request, scope="function"):
    """Return True when resources should be retained on teardown based on CLI options.

    - Always True when --no-delete is set.
    - True when --retain-on-failure > 0 and there is a failure in the current scope,
      but only up to --retain-on-failure failed tests (shared across xdist workers):
        * For function/class-scoped fixtures, the failure is taken from the current test item
          and the test is registered in the shared retain file.
    """
    if request.config.getoption("no_delete"):
        return True
    if request.config.getoption("retain_on_failure"):
        # For function/class-scoped fixtures, check if the current test failed
        # and register it for retention if within the limit.
        if scope == "function":
            failed = _current_test_failed(request)
            test_id = request.node.nodeid
        else:
            failed = _any_test_failed_in_session(request)
            failed_tests = getattr(request.session, "_pcluster_failed_tests", None)
            test_id = next(iter(failed_tests)) if failed_tests else "unknown"

        if not failed:
            return False

        within_limit, current_count, max_retain = _record_test_id_for_retention(request, test_id)
        if within_limit:
            logging.warning(
                "Retaining resources because --retain-on-failure is set and a test failed (%d/%d)",
                current_count,
                max_retain,
            )
            return True
        else:
            logging.info(
                "Not retaining resources: retain-on-failure limit reached (%d/%d)",
                current_count,
                max_retain,
            )
            return False
    return False
