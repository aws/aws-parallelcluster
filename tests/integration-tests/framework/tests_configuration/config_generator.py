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
import logging
import os
from collections import OrderedDict
from pathlib import Path

import argparse
from framework.tests_configuration.config_utils import discover_all_test_functions
from jinja2 import Environment, FileSystemLoader

package_directory = os.path.dirname(os.path.abspath(__file__))
CONFIG_STUB_FILE = f"{package_directory}/config_stub.yaml.jinja2"


def _auto_generate_config(tests_root_dir):
    test_functions = discover_all_test_functions(tests_root_dir)

    sorted_test_functions = OrderedDict()
    for key in sorted(test_functions):
        sorted_test_functions[key] = test_functions[key]

    config_dir = os.path.dirname(CONFIG_STUB_FILE)
    config_name = os.path.basename(CONFIG_STUB_FILE)
    file_loader = FileSystemLoader(config_dir)
    env = Environment(loader=file_loader)
    rendered_template = env.get_template(config_name).render(test_functions=sorted_test_functions)

    return rendered_template


if __name__ == "__main__":
    logging.basicConfig(format="%(levelname)s - %(message)s", level=logging.DEBUG)

    parser = argparse.ArgumentParser(
        description="Utility module used to generate stub for tests config. "
        "All existing integration tests are automatically discovered and a test config file is "
        "automatically generated from them.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--output-file", help="File where to write the generated config.", required=True)
    parser.add_argument(
        "--tests-root-dir",
        help="Root dir where integration tests are defined",
        required=True,
    )
    args = parser.parse_args()

    generated_config = _auto_generate_config(args.tests_root_dir)
    logging.info("Writing generated config to %s", args.output_file)
    Path(args.output_file).write_text(generated_config)
