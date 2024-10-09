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
from datetime import date
from functools import lru_cache

import yaml
from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment
from utils import InstanceTypesData

from pcluster.constants import SUPPORTED_OSES


def _get_os_parameters(config=None, args=None):
    """
    Gets OS jinja parameters.
    The input could be args from arg parser or config from pytest. This function is used both by arg parser and pytest.
    :param args: args from arg parser
    :param config: config from pytest
    """
    available_amis_oss_x86 = _get_available_amis_oss("x86", config=config, args=args)
    available_amis_oss_arm = _get_available_amis_oss("arm", config=config, args=args)
    result = {}
    today_number = (date.today() - date(2020, 1, 1)).days
    for index in range(len(SUPPORTED_OSES)):
        result[f"OS_X86_{index}"] = available_amis_oss_x86[(today_number + index) % len(available_amis_oss_x86)]
        result[f"OS_ARM_{index}"] = available_amis_oss_arm[(today_number + index) % len(available_amis_oss_arm)]
    return result


def _get_available_amis_oss(architecture, args=None, config=None):
    """
    Gets available AMIs for given architecture from input.
    The input could be args from arg parser or config from pytest. This function is used both by arg parser and pytest.
    :param architecture:  The architecture of the OS (x86 or arm)
    :param args: args from arg parser
    :param config: config from pytest
    :return: list of available AMIs from input or all supported AMIs if input is not provided
    :rtype: list
    """
    available_amis_oss = None
    if args:
        args_dict = vars(args)
        available_amis_oss = args_dict.get(f"available_amis_oss_{architecture}")
    elif config and config.getoption(f"available_amis_oss_{architecture}"):
        available_amis_oss = config.getoption(f"available_amis_oss_{architecture}").split(" ")
    if available_amis_oss:
        logging.info("Using available %s AMIs OSes from input", architecture)
        return available_amis_oss
    else:
        logging.info(
            "Using all supported x86 OSes because the list of available %s AMIs OSes is not provided.", architecture
        )
        return SUPPORTED_OSES


def read_config_file(config_file, print_rendered=False, config=None, args=None, **kwargs):
    """
    Read the test config file and apply Jinja rendering.
    Multiple invocations of the same function within the same process produce the same rendering output. This is done
    in order to produce a consistent result in case random values are selected in jinja templating logic.

    :param config_file: path to the config file to read
    :param print_rendered: log rendered config file
    :return: a dict containig the parsed config file
    """
    logging.info("Parsing config file: %s", config_file)
    rendered_config = _render_config_file(config_file, **kwargs, **_get_os_parameters(config=config, args=args))
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
