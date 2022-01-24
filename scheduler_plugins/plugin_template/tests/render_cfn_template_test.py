#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.

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
import hashlib
import json
import logging
import os
import subprocess
import sys
from tempfile import NamedTemporaryFile

import yaml
from cfn_tools import dump_yaml, load_yaml
from jinja2 import Environment, FileSystemLoader

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)


def test_render_cfn_template():
    config = _read_yaml_file(os.path.join(os.path.dirname(__file__), "./resources/cluster_config.yaml"))
    instance_types_info = _read_json_file(os.path.join(os.path.dirname(__file__), "./resources/instance_types_info.json"))
    print(f"Configuration file:\n{_dump_yaml(config)}")
    rendered_template = _render_template(
        os.path.join(os.path.dirname(__file__), "../additional_cluster_infrastructure.cfn.yaml"),
        config,
        instance_types_info
    )
    print(f"Template:\n{dump_yaml(load_yaml(rendered_template))}")
    with NamedTemporaryFile(mode="w") as f:
        f.write(rendered_template)
        f.flush()
        subprocess.check_call(["cfn-lint", "-i", "W2001", "W8001", "--", f.name])


def _read_yaml_file(file):
    """Read the test config file."""
    try:
        with open(file, "r") as f:
            return yaml.safe_load(f)
    except Exception:
        logging.exception("Failed when reading file %s", file)
        raise


def _read_json_file(file):
    """Read the test config file."""
    try:
        with open(file, "r") as f:
            return json.load(f)
    except Exception:
        logging.exception("Failed when reading file %s", file)
        raise


def _dump_yaml(config):
    """Write config to file"""
    return yaml.dump(config, default_flow_style=False)


def _render_template(template, config, instance_types_info):
    """Apply Jinja rendering to the specified file."""
    try:
        file_loader = FileSystemLoader(os.path.dirname(template))
        environment = Environment(loader=file_loader)
        environment.filters["hash"] = (
            lambda value: hashlib.sha1(value.encode()).hexdigest()[0:16].capitalize()
        )
        return (
            environment.get_template(os.path.basename(template)).render(
                cluster_configuration=config, cluster_name="name", instance_types_info=instance_types_info)
        )
    except Exception as e:
        logging.error("Failed when rendering config file %s with error: %s", template, e)
        raise


if __name__ == "__main__":
    test_render_cfn_template()
