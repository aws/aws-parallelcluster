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
import os
from functools import lru_cache

import yaml
from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment
from utils import InstanceTypesData


def read_config_file(config_file, print_rendered=False, **kwargs):
    """
    Read the test config file and apply Jinja rendering.
    Multiple invocations of the same function within the same process produce the same rendering output. This is done
    in order to produce a consistent result in case random values are selected in jinja templating logic.

    :param config_file: path to the config file to read
    :param print_rendered: log rendered config file
    :return: a dict containig the parsed config file
    """
    logging.info("Parsing config file: %s", config_file)
    rendered_config = _render_config_file(config_file, **kwargs)
    try:
        return yaml.safe_load(rendered_config)
    except Exception:
        logging.exception("Failed when reading config file %s", config_file)
        print_rendered = True
        raise
    finally:
        if print_rendered:
            logging.info("Dumping rendered template:\n%s", rendered_config)


def dump_rendered_config_file(config):
    """Write config to file"""
    return yaml.dump(config, default_flow_style=False)


@lru_cache(maxsize=None)
def _render_config_file(config_file, **kwargs):
    """
    Apply Jinja rendering to the specified config file.

    Multiple invocations of this function with same args will produce the same rendering output.
    """
    try:
        config_dir = os.path.dirname(config_file)
        config_name = os.path.basename(config_file)
        file_loader = FileSystemLoader(config_dir)
        return (
            SandboxedEnvironment(loader=file_loader)
            .get_template(config_name)
            .render(additional_instance_types_map=InstanceTypesData.additional_instance_types_map, **kwargs)
        )
    except Exception as e:
        logging.error("Failed when rendering config file %s with error: %s", config_file, e)
        raise
