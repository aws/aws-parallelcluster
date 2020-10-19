# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import json
import logging
import os
from copy import deepcopy

import argparse
from assertpy import assert_that, soft_assertions
from framework.tests_configuration.config_renderer import dump_rendered_config_file, read_config_file
from framework.tests_configuration.config_utils import discover_all_test_functions
from pykwalify.core import Core

package_directory = os.path.dirname(os.path.abspath(__file__))
CONFIG_SCHEMA = f"{package_directory}/config_schema.yaml"


def assert_valid_config(config, tests_root_dir):
    """
    Validate the provided test config file by performing the following actions:
    - Validate the YAML schema of the config
    - Check that the tests defined in the config file actually exist
    - Check that the provided dimensions are not all empty

    :param config: dict containing the parsed config file
    :param tests_root_dir: root dir where integration tests are defined
    """
    _validate_against_schema(config)
    _check_declared_tests_exist(config, tests_root_dir)
    _check_no_empty_dimension_lists(config)


def _check_no_empty_dimension_lists(config):
    """Verify that at least one dimension is not an empty list"""
    logging.info("Checking provided dimensions are valid")
    for feature in config.get("test-suites").values():
        for test_name, test in feature.items():
            for dimensions_config in test.values():
                for dimensions_group in dimensions_config:
                    if [] in dimensions_group.values():
                        logging.error("Values assigned to dimensions in test %s cannot be empty", test_name)
                        raise AssertionError


def _validate_against_schema(config):
    """Verify that config file is compliant with the defined schema"""
    logging.info("Validating config file against the schema")
    try:
        c = Core(source_data=config, schema_files=[CONFIG_SCHEMA])
        c.validate(raise_exception=True)
    except Exception as e:
        logging.error("Failed when validating schema: %s", e)
        logging.info("Dumping rendered template:\n%s", dump_rendered_config_file(config))
        raise


def _check_declared_tests_exist(config, tests_root_dir):
    """Check that all the tests declared in the config file correspond to actual valid test functions"""
    logging.info("Checking that configured tests exist")
    test_functions = discover_all_test_functions(tests_root_dir)
    unused_test_functions = deepcopy(test_functions)
    try:
        with soft_assertions():
            for dirname, configured_tests in config["test-suites"].items():
                assert_that(test_functions).contains_key(dirname)
                assert_that(test_functions.get(dirname, [])).contains(*[test for test in configured_tests.keys()])
                unused_test_functions[dirname] = list(unused_test_functions[dirname] - configured_tests.keys())
    except AssertionError as e:
        logging.error("Some of the configured tests do not exist: %s", e)
        raise

    logging.info("Found following unused test functions: %s", json.dumps(unused_test_functions, indent=2))


if __name__ == "__main__":
    logging.basicConfig(format="%(levelname)s - %(message)s", level=logging.DEBUG)
    logging.getLogger("pykwalify").setLevel(logging.INFO)

    parser = argparse.ArgumentParser(
        description="Validate tests config.", formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--tests-config-file",
        help="Tests config file to validate",
    )
    group.add_argument(
        "--tests-configs-dir",
        help="Directory containing tests config files to validate",
    )
    parser.add_argument(
        "--tests-root-dir",
        help="Root dir where integration tests are defined",
        required=True,
    )
    args = parser.parse_args()

    if args.tests_config_file:
        assert_valid_config(read_config_file(args.tests_config_file, print_rendered=True), args.tests_root_dir)
    else:
        for filename in os.listdir(args.tests_configs_dir):
            if filename.endswith(".yaml.jinja2") or filename.endswith(".yaml"):
                assert_valid_config(
                    read_config_file(os.path.join(args.tests_configs_dir, filename), print_rendered=True),
                    args.tests_root_dir,
                )
