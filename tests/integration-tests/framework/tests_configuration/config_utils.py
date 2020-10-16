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
import json
import logging
import os
from collections import OrderedDict
from importlib._bootstrap import module_from_spec
from importlib._bootstrap_external import spec_from_file_location
from pathlib import Path


def get_enabled_tests(config):
    """
    Build a set containing all tests defined in the config file.

    Each entry of the set is in the format {test-suite}/{test-module}::{test-function},
    e.g. 'cfn-init/test_cfn_init.py::test_replace_compute_on_failure'
    """
    enabled_test_suites = config.get("test-suites")
    enabled_tests = set()
    for suite, tests in enabled_test_suites.items():
        for test in tests.keys():
            enabled_tests.add("{0}/{1}".format(suite, test))

    return enabled_tests


def get_all_regions(config):
    """Retrieve a set of all regions used by the declared integration tests."""
    regions = set()
    for feature in config.get("test-suites").values():
        for test in feature.values():
            for dimensions_config in test.values():
                for dimensions_group in dimensions_config:
                    regions.update(dimensions_group.get("regions", []))
    return regions


def discover_all_test_functions(tests_root_dir):
    """
    Discover all defined test functions by dynamically loading all test modules.

    e.g. of the returned dict:
    {
      "cloudwatch_logging": [
        "test_cloudwatch_logging.py::test_cloudwatch_logging"
      ],
      "dcv": [
        "test_dcv.py::test_dcv_configuration",
        "test_dcv.py::test_dcv_with_remote_access"
      ],
      ...
    }

    :param tests_root_dir: root dir where looking for test modules.
    :return: a dict containing the discovered test modules and test functions.
    """
    logging.info("Collecting all existing test functions")
    test_module_paths = list(Path(tests_root_dir).rglob("test_*.py"))
    discovered_test_functions = OrderedDict()
    for module_path in test_module_paths:
        module_filename = os.path.basename(str(module_path))
        module_dirname = os.path.split(os.path.dirname(str(module_path)))[-1]
        spec = spec_from_file_location(os.path.splitext(module_filename)[0], module_path)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        test_functions = filter(lambda func_name: func_name.startswith("test_"), dir(module))
        test_functions_identifiers = [f"{module_filename}::{test_function}" for test_function in test_functions]
        discovered_test_functions[module_dirname] = (
            discovered_test_functions.get(module_dirname, []) + test_functions_identifiers
        )

    logging.info("Discovered following test functions:\n%s", json.dumps(discovered_test_functions, indent=2))
    return discovered_test_functions
