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

import boto3
import yaml
from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment
from utils import InstanceTypesData

from pcluster.constants import SUPPORTED_OSES, UNSUPPORTED_ARM_OSES_FOR_DCV, UNSUPPORTED_OSES_FOR_DCV


def _get_os_parameters(config=None, args=None):
    """
    Gets OS jinja parameters.
    The input could be args from arg parser or config from pytest. This function is used both by arg parser and pytest.
    :param args: args from arg parser
    :param config: config from pytest
    """
    available_amis_oss_x86 = _get_available_amis_oss("x86", config=config, args=args)
    available_amis_oss_arm = _get_available_amis_oss("arm", config=config, args=args)
    result = {"AVAILABLE_AMIS_OSS_X86": available_amis_oss_x86, "AVAILABLE_AMIS_OSS_ARM": available_amis_oss_arm}
    today_number = (date.today() - date(2020, 1, 1)).days
    for index in range(len(SUPPORTED_OSES)):
        result[f"OS_X86_{index}"] = available_amis_oss_x86[(today_number + index) % len(available_amis_oss_x86)]
        result[f"OS_ARM_{index}"] = available_amis_oss_arm[(today_number + index) % len(available_amis_oss_arm)]

    # DCV doesn't support AL2023. Therefore, the following logic makes sure the DCV jinja parameter is not AL2023
    dcv_supported_oses = [os for os in SUPPORTED_OSES if os not in UNSUPPORTED_OSES_FOR_DCV]
    dcv_supported_arm_oses = [
        os for os in SUPPORTED_OSES if os not in UNSUPPORTED_OSES_FOR_DCV + UNSUPPORTED_ARM_OSES_FOR_DCV
    ]
    dcv_available_amis_oss_x86 = list(set(dcv_supported_oses) & set(available_amis_oss_x86))
    dcv_available_amis_oss_arm = list(set(dcv_supported_arm_oses) & set(available_amis_oss_arm))
    for index in range(len(dcv_supported_oses)):
        result[f"DCV_OS_X86_{index}"] = dcv_available_amis_oss_x86[
            (today_number + index) % len(dcv_available_amis_oss_x86)
        ]
        result[f"DCV_OS_ARM_{index}"] = dcv_available_amis_oss_arm[
            (today_number + index) % len(dcv_available_amis_oss_arm)
        ]

    no_rhel_oss = [os for os in SUPPORTED_OSES if "rhel" not in os]
    no_rhel_oss_x86 = list(set(no_rhel_oss) & set(available_amis_oss_x86))
    no_rhel_oss_arm = list(set(no_rhel_oss) & set(available_amis_oss_arm))
    for index in range(len(no_rhel_oss)):
        result[f"NO_RHEL_OS_X86_{index}"] = no_rhel_oss_x86[(today_number + index) % len(no_rhel_oss_x86)]
        result[f"NO_RHEL_OS_ARM_{index}"] = no_rhel_oss_arm[(today_number + index) % len(no_rhel_oss_arm)]
    return result


def _get_instance_type_parameters():  # noqa: C901
    """Gets Instance jinja parameters."""
    result = {}
    excluded_instance_type_prefixes = [
        "m1",
        "m2",
        "m3",
        "m4",
        "t1",
        "t2",
        "c1",
        "c3",
        "c4",
        "r3",
        "r4",
        "x1",
        "x1e",
        "d2",
        "h1",
        "i2",
        "i3",
        "f1",
        "g3",
        "p2",
        "p3",
    ]
    for region in ["us-east-1", "us-west-2", "eu-west-1"]:  # Only populate instance type for big regions
        ec2_client = boto3.client("ec2", region_name=region)
        # The following conversion is required becase Python jinja doesn't like "-"
        region_jinja = region.replace("-", "_").upper()
        try:
            xlarge_instances = []
            instance_type_availability_zones = {}
            # Use describe_instance_types with pagination
            paginator = ec2_client.get_paginator("describe_instance_type_offerings")

            for page in paginator.paginate(LocationType="availability-zone"):
                for instance_type in page["InstanceTypeOfferings"]:
                    # Check if instance type ends with '.xlarge'
                    if instance_type["InstanceType"].endswith(".xlarge") and not any(
                        instance_type["InstanceType"].startswith(prefix) for prefix in excluded_instance_type_prefixes
                    ):
                        xlarge_instances.append(instance_type["InstanceType"])
                        if instance_type_availability_zones.get(instance_type["InstanceType"]):
                            instance_type_availability_zones[instance_type["InstanceType"]].append(
                                instance_type["Location"]
                            )
                        else:
                            instance_type_availability_zones[instance_type["InstanceType"]] = [
                                instance_type["Location"]
                            ]

            xlarge_instances = list(set(xlarge_instances))  # Remove redundancy.
            gpu_instances = []
            paginator = ec2_client.get_paginator("describe_instance_types")
            for page in paginator.paginate(InstanceTypes=xlarge_instances):
                for instance_type in page["InstanceTypes"]:
                    if instance_type.get("GpuInfo"):
                        gpu_instances.append(instance_type["InstanceType"])

            xlarge_instances.sort()
            gpu_instances.sort()
            today_number = (date.today() - date(2020, 1, 1)).days
            for index in range(len(xlarge_instances)):
                instance_type = xlarge_instances[(today_number + index) % len(xlarge_instances)]
                result[f"{region_jinja}_INSTANCE_TYPE_{index}"] = instance_type[: -len(".xlarge")]
                availability_zones = instance_type_availability_zones[instance_type]
                result[f"{region_jinja}_INSTANCE_TYPE_{index}_AZ"] = (
                    availability_zones[0] if len(availability_zones) <= 2 else region
                )
            for index in range(len(gpu_instances)):
                instance_type = gpu_instances[(today_number + index) % len(gpu_instances)]
                result[f"{region_jinja}_GPU_INSTANCE_TYPE_{index}"] = instance_type[: -len(".xlarge")]
                availability_zones = instance_type_availability_zones[instance_type]
                result[f"{region_jinja}_GPU_INSTANCE_TYPE_{index}_AZ"] = (
                    availability_zones[0] if len(availability_zones) <= 2 else region
                )
        except Exception as e:
            print(f"Error getting instance types: {str(e)}. Using c5 and g4dn as the default instance type")
            for index in range(100):
                result[f"{region_jinja}_INSTANCE_TYPE_{index}"] = "c5"
                result[f"{region_jinja}_INSTANCE_TYPE_{index}_AZ"] = region
            for index in range(10):
                result[f"{region_jinja}_GPU_INSTANCE_TYPE_{index}"] = "g4dn"
                result[f"{region_jinja}_GPU_INSTANCE_TYPE_{index}_AZ"] = region
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
    rendered_config = _render_config_file(
        config_file, **kwargs, **_get_os_parameters(config=config, args=args), **_get_instance_type_parameters()
    )
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
