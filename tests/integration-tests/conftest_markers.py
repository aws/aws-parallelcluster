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

DIMENSIONS_MARKER_ARGS = ["region", "instance", "os", "scheduler"]
UNSUPPORTED_DIMENSIONS = [
    ("eu-north-1", "c4.xlarge", "*", "*"),
    ("eu-west-3", "c4.xlarge", "*", "*"),
    ("ap-east-1", "c4.xlarge", "*", "*"),
    ("*", "*", "centos7", "awsbatch"),
    ("*", "*", "centos8", "awsbatch"),
    ("*", "*", "ubuntu1804", "awsbatch"),
    ("*", "*", "ubuntu1604", "awsbatch"),
    ("us-gov-east-1", "*", "c4.xlarge", "*"),
]


class InvalidMarkerError(Exception):
    """Error raised with marker is invalid"""

    pass


def _add_unsupported_arm_dimensions():
    """Add invalid dimensions due to lack of ARM instance types in some regions and ARM AMIs for certain OSes."""
    arm_instance_types = ["m6g.xlarge"]
    oses_unsupported_by_arm = ["centos7", "alinux", "ubuntu1604"]
    regions_unsupported_by_arm = [
        "us-west-1",
        "ca-central-1",
        "eu-west-2",
        "eu-west-3",
        "sa-east-1",
        "ap-east-1",
        "ap-northeast-2",
        "ap-south-1",
        "ap-southeast-1",
        "ap-southeast-2",
        "eu-north-1",
        "us-gov-west-1",
        "us-gov-east-1",
        "cn-north-1",
        "cn-northwest-1",
    ]
    for instance_type in arm_instance_types:
        for unsupported_os in oses_unsupported_by_arm:
            UNSUPPORTED_DIMENSIONS.append(("*", instance_type, unsupported_os, "*"))
        for unsupported_region in regions_unsupported_by_arm:
            UNSUPPORTED_DIMENSIONS.append((unsupported_region, instance_type, "*", "*"))


def add_default_markers(items):
    """
    Add default markers for dimensions that need to be skipped by default for all tests.

    :param items: pytest Item object markers are applied to.
    """
    _add_unsupported_arm_dimensions()
    for item in items:
        for dimensions in UNSUPPORTED_DIMENSIONS:
            item.add_marker(pytest.mark.skip_dimensions(*dimensions))


def check_marker_list(items, marker_name, arg_name):
    """
    Skip all tests that are annotated with marker marker_name and have the arg value corresponding to arg_name
    not listed in the list passed as first argument to the marker.

    Example:
        @pytest.mark.marker_name(["value1", "value2"])
        def test(arg_name)

        The test is executed only if arg_name is equal to "value1" or "value2".

    :param items: pytest Item objects annotated with markers.
    :param marker_name: name of the marker to process.
    :param arg_name: arg name the marker values should be compared to.
    """
    for item in list(items):
        arg_value = item.callspec.params.get(arg_name)
        allowed_values = []
        for marker in item.iter_markers(name=marker_name):
            _validate_marker(marker_name, [marker_name + "_list"], len(marker.args))
            allowed_values.extend(marker.args[0])

        if not allowed_values or arg_value in allowed_values:
            continue
        skip_message = (
            "Skipping test {test_name} because {arg_name} {arg_value} is not in {marker} allowed values: "
            "{allowed_values}".format(
                test_name=item.name,
                arg_name=arg_name,
                arg_value=arg_value,
                marker=marker_name,
                allowed_values=allowed_values,
            )
        )
        logging.debug(skip_message)
        items.remove(item)


def check_marker_skip_list(items, marker_name, arg_name):
    """
    Skip all tests that are annotated with marker marker_name and have the arg value corresponding to arg_name
    listed in the list passed as first argument to the marker.

    Example:
        @pytest.mark.marker_name(["value1", "value2"])
        def test(arg_name)

        The test is executed only if arg_name is not equal to "value1" or "value2".

    :param items: pytest Item objects annotated with markers.
    :param marker_name: name of the marker to process.
    :param arg_name: arg name the marker values should be compared to.
    """
    for item in list(items):
        arg_value = item.callspec.params.get(arg_name)
        for marker in item.iter_markers(name=marker_name):
            _validate_marker(marker_name, [marker_name + "_skip_list"], len(marker.args))
            skip_values = marker.args[0]
            if arg_value in skip_values:
                skip_message = (
                    "Skipping test {test_name} because {arg_name} {arg_value} is in {marker} allowed values:"
                    "{skip_values}".format(
                        test_name=item.name,
                        arg_name=arg_name,
                        arg_value=arg_value,
                        marker=marker_name,
                        skip_values=skip_values,
                    )
                )
                logging.debug(skip_message)
                items.remove(item)


def check_marker_skip_dimensions(items):
    """
    Skip all tests that are annotated with @pytest.mark.skip_dimensions and have the args
    (region, instance, os, scheduler) match those specified in the marker.

    "*" can be used to identify all values for a specific argument.

    Example:
        @pytest.mark.skip_dimensions("a", "b", "*", "d")
        def test(region, instance, os, scheduler)

        The test is executed only if the test args (region, instance, os, scheduler) do not match
        ("a", "b", "*", "d")

    :param items: pytest Item objects annotated with markers.
    """
    marker_name = "skip_dimensions"
    for item in list(items):
        args_values = []
        for dimension in DIMENSIONS_MARKER_ARGS:
            args_values.append(item.callspec.params.get(dimension))
        for marker in item.iter_markers(name=marker_name):
            _validate_marker(marker_name, DIMENSIONS_MARKER_ARGS, len(marker.args))
            if len(marker.args) != len(DIMENSIONS_MARKER_ARGS):
                logging.error(
                    "Marker {marker_name} requires the following args: {args}".format(
                        marker_name=marker_name, args=DIMENSIONS_MARKER_ARGS
                    )
                )
                raise ValueError
            dimensions_match = _compare_dimension_lists(args_values, marker.args)
            if dimensions_match:
                skip_message = (
                    "Skipping test {test_name} because dimensions {args_values} match {marker}: "
                    "{skip_values}".format(
                        test_name=item.name, args_values=args_values, marker=marker_name, skip_values=marker.args
                    )
                )
                logging.debug(skip_message)
                items.remove(item)
                break


def check_marker_dimensions(items):
    """
    Execute all tests that are annotated with @pytest.mark.dimensions and have the args
    (region, instance, os, scheduler) match those specified in the marker.

    "*" can be used to identify all values for a specific argument.

    Example:
        @pytest.mark.dimensions("a", "b", "*", "d")
        def test(region, instance, os, scheduler)

        The test is executed only if the test args (region, instance, os, scheduler) match ("a", "b", "*", "d")

    :param items: pytest Item objects annotated with markers.
    """
    marker_name = "dimensions"
    for item in list(items):
        test_args_value = []
        for dimension in DIMENSIONS_MARKER_ARGS:
            test_args_value.append(item.callspec.params.get(dimension))
        allowed_values = []
        dimensions_match = False
        for marker in item.iter_markers(name=marker_name):
            _validate_marker(marker_name, DIMENSIONS_MARKER_ARGS, len(marker.args))
            allowed_values.append(marker.args)
            dimensions_match = _compare_dimension_lists(test_args_value, marker.args)
            if dimensions_match:
                break

        if not dimensions_match and allowed_values:
            skip_message = (
                "Skipping test {test_name} because dimensions {test_args_value} do not match any marker {marker}"
                " values: {allowed_values}".format(
                    test_name=item.name,
                    test_args_value=test_args_value,
                    marker=marker_name,
                    allowed_values=allowed_values,
                )
            )
            logging.debug(skip_message)
            items.remove(item)


def _validate_marker(marker_name, expected_args, args_count):
    if args_count != len(expected_args):
        logging.error(
            "Marker {marker_name} requires the following args: {args}".format(
                marker_name=marker_name, args=expected_args
            )
        )
        raise InvalidMarkerError


def _compare_dimension_lists(list1, list2):
    if len(list1) != len(list2):
        return False
    for d1, d2 in zip(list1, list2):
        if d1 != "*" and d2 != "*" and d1 != d2:
            return False
    return True
