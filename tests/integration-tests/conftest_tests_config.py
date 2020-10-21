import logging
import os
from itertools import product

from conftest_markers import DIMENSIONS_MARKER_ARGS
from framework.tests_configuration.config_utils import get_enabled_tests
from xdist import get_xdist_worker_id


def parametrize_from_config(metafunc):
    """
    Apply parametrization to all test functions loaded by pytest.

    The functions discovered by pytest are matched against the ones declared in the test config file. When a match
    if found, meaning the test is enabled, the dimensions declared in the config file are applied to the test function.
    """
    tests_config = metafunc.config.getoption("tests_config")
    test_collection_name = metafunc.definition.nodeid.split(os.path.sep)[0]
    test_name = metafunc.definition.nodeid.split(os.path.sep)[1]
    if test_collection_name in tests_config["test-suites"]:
        if test_name in tests_config["test-suites"][test_collection_name]:
            configured_dimensions_items = tests_config["test-suites"][test_collection_name][test_name]["dimensions"]
            argnames, argvalues = _get_combinations_of_dimensions_values(configured_dimensions_items)
            if argvalues:
                metafunc.parametrize(argnames, argvalues, scope="class")


def _get_combinations_of_dimensions_values(configured_dimensions_items):
    """
    Given a list of dict defining the configured test dimensions it computes all combinations of dimension
    values in order to parametrize the tests.

    E.g.
    configured_dimensions_items =
      [{'instances': ['inst1'], 'oss': ['os1', 'os2'], 'regions': ['region1', 'region2'], 'schedulers': ['s']},
       {'instances': ['inst2', 'inst3'], 'oss': ['os1'], 'regions': ['region3'], 'schedulers': ['s']}]

    Produces the following output:
      argvalues = [('region1', 'inst1', 'os1', 's'), ('region1', 'inst1', 'os2', 's'), ('region2', 'inst1', 'os1', 's'),
                   ('region2', 'inst1', 'os2', 's'), ('region3', 'inst2', 'os1', 's'), ('region3', 'inst3', 'os1', 's')]
    """
    argnames = list(DIMENSIONS_MARKER_ARGS)
    argvalues = []
    for item in configured_dimensions_items:
        dimensions_values = []
        for dim in DIMENSIONS_MARKER_ARGS:
            values = item.get(f"{dim}s")
            if values:
                dimensions_values.append(values)
            elif dim in argnames:
                argnames.remove(dim)
        argvalues.extend(list(product(*dimensions_values)))

    return argnames, argvalues


def remove_disabled_tests(session, config, items):
    """Remove all tests that are not defined in the config file"""
    enabled_tests = get_enabled_tests(config.getoption("tests_config"))
    for item in list(items):
        if item.nodeid.split("[")[0] not in enabled_tests:
            if get_xdist_worker_id(session) in ["master", "gw0"]:
                # log only in master process to avoid duplicate log entries
                logging.warning("Skipping test %s because not defined in config", item.nodeid)
            items.remove(item)


def apply_cli_dimensions_filtering(config, items):
    """Filter tests based on dimensions passed as cli arguments."""
    allowed_values = {}
    for dimension in DIMENSIONS_MARKER_ARGS:
        allowed_values[dimension] = config.getoption(dimension + "s")
    for item in list(items):
        for dimension in DIMENSIONS_MARKER_ARGS:
            # callspec is not set if parametrization did not happen
            if hasattr(item, "callspec"):
                arg_value = item.callspec.params.get(dimension)
                if allowed_values[dimension]:
                    if arg_value not in allowed_values[dimension]:
                        items.remove(item)
                        break
