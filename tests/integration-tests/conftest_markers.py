import logging

import pytest

DIMENSIONS_MARKER_ARGS = ["region", "instance", "os", "scheduler"]
UNSUPPORTED_DIMENSIONS = [("eu-north-1", "c4.xlarge", "*", "*"), ("eu-west-3", "c4.xlarge", "*", "*")]


class InvalidMarkerError(Exception):
    """Error raised with marker is invalid"""

    pass


def add_default_markers(item):
    """
    Add default markers for dimensions that need to be skipped by default for all tests.

    :param item: pytest Item object markers are applied to.
    """
    for dimensions in UNSUPPORTED_DIMENSIONS:
        item.add_marker(pytest.mark.skip_dimensions(*dimensions))


def check_marker_list(item, marker_name, arg_name):
    """
    Skip all tests that are annotated with marker marker_name and have the arg value corresponding to arg_name
    not listed in the list passed as first argument to the marker.

    Example:
        @pytest.mark.marker_name(["value1", "value2"])
        def test(arg_name)

        The test is executed only if arg_name is equal to "value1" or "value2".

    :param item: pytest Item object annotated with markers.
    :param marker_name: name of the marker to process.
    :param arg_name: arg name the marker values should be compared to.
    """
    arg_value = item.funcargs.get(arg_name)
    allowed_values = []
    for marker in item.iter_markers(name=marker_name):
        _validate_marker(marker_name, [marker_name + "_list"], len(marker.args))
        allowed_values.extend(marker.args[0])

    if not allowed_values or arg_value in allowed_values:
        return
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
    logging.info(skip_message)
    pytest.skip(skip_message)


def check_marker_skip_list(item, marker_name, arg_name):
    """
    Skip all tests that are annotated with marker marker_name and have the arg value corresponding to arg_name
    listed in the list passed as first argument to the marker.

    Example:
        @pytest.mark.marker_name(["value1", "value2"])
        def test(arg_name)

        The test is executed only if arg_name is not equal to "value1" or "value2".

    :param item: pytest Item object annotated with markers.
    :param marker_name: name of the marker to process.
    :param arg_name: arg name the marker values should be compared to.
    """
    arg_value = item.funcargs.get(arg_name)
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
            logging.info(skip_message)
            pytest.skip(skip_message)


def check_marker_skip_dimensions(item):
    """
    Skip all tests that are annotated with @pytest.mark.skip_dimensions and have the args
    (region, instance, os, scheduler) match those specified in the marker.

    "*" can be used to identify all values for a specific argument.

    Example:
        @pytest.mark.skip_dimensions("a", "b", "*", "d")
        def test(region, instance, os, scheduler)

        The test is executed only if the test args (region, instance, os, scheduler) do not match
        ("a", "b", "*", "d")

    :param item: pytest Item object annotated with markers.
    """
    marker_name = "skip_dimensions"
    args_values = []
    for dimension in DIMENSIONS_MARKER_ARGS:
        args_values.append(item.funcargs.get(dimension))
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
            logging.info(skip_message)
            pytest.skip(skip_message)


def check_marker_dimensions(item):
    """
    Execute all tests that are annotated with @pytest.mark.dimensions and have the args
    (region, instance, os, scheduler) match those specified in the marker.

    "*" can be used to identify all values for a specific argument.

    Example:
        @pytest.mark.dimensions("a", "b", "*", "d")
        def test(region, instance, os, scheduler)

        The test is executed only if the test args (region, instance, os, scheduler) match ("a", "b", "*", "d")

    :param item: pytest Item object annotated with markers.
    """
    marker_name = "dimensions"
    test_args_value = []
    for dimension in DIMENSIONS_MARKER_ARGS:
        test_args_value.append(item.funcargs.get(dimension))
    allowed_values = []
    for marker in item.iter_markers(name=marker_name):
        _validate_marker(marker_name, DIMENSIONS_MARKER_ARGS, len(marker.args))
        allowed_values.append(marker.args)
        dimensions_match = _compare_dimension_lists(test_args_value, marker.args)
        if dimensions_match:
            return

    if allowed_values:
        skip_message = (
            "Skipping test {test_name} because dimensions {test_args_value} do not match any marker {marker} values: "
            "{allowed_values}".format(
                test_name=item.name, test_args_value=test_args_value, marker=marker_name, allowed_values=allowed_values
            )
        )
        logging.info(skip_message)
        pytest.skip(skip_message)


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
