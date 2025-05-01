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
import re
from datetime import date, datetime, timedelta, timezone

import boto3
import yaml
from jinja2 import FileSystemLoader, meta
from jinja2.sandbox import SandboxedEnvironment
from utils import InstanceTypesData

from pcluster.constants import (
    SUPPORTED_OSES,
    SUPPORTED_OSES_FOR_SCHEDULER,
    UNSUPPORTED_ARM_OSES_FOR_DCV,
    UNSUPPORTED_OSES_FOR_DCV,
    UNSUPPORTED_OSES_FOR_LUSTRE,
)


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

    batch_supported_oses = SUPPORTED_OSES_FOR_SCHEDULER["awsbatch"]
    batch_available_amis_oss_x86 = list(set(batch_supported_oses) & set(available_amis_oss_x86))
    batch_available_amis_oss_arm = list(set(batch_supported_oses) & set(available_amis_oss_arm))
    for index in range(len(batch_supported_oses)):
        result[f"BATCH_OS_X86_{index}"] = batch_available_amis_oss_x86[
            (today_number + index) % len(batch_available_amis_oss_x86)
        ]
        result[f"BATCH_OS_ARM_{index}"] = batch_available_amis_oss_arm[
            (today_number + index) % len(batch_available_amis_oss_arm)
        ]

    lustre_supported_oses = [os for os in SUPPORTED_OSES if os not in UNSUPPORTED_OSES_FOR_LUSTRE]
    lustre_available_amis_oss_x86 = list(set(lustre_supported_oses) & set(available_amis_oss_x86))
    lustre_available_amis_oss_arm = list(set(lustre_supported_oses) & set(available_amis_oss_arm))
    for index in range(len(dcv_supported_oses)):
        result[f"LUSTRE_OS_X86_{index}"] = lustre_available_amis_oss_x86[
            (today_number + index) % len(lustre_available_amis_oss_x86)
        ]
        result[f"LUSTRE_OS_ARM_{index}"] = lustre_available_amis_oss_arm[
            (today_number + index) % len(lustre_available_amis_oss_arm)
        ]

    no_rhel_oss = [os for os in SUPPORTED_OSES if "rhel" not in os]
    no_rhel_oss_x86 = list(set(no_rhel_oss) & set(available_amis_oss_x86))
    no_rhel_oss_arm = list(set(no_rhel_oss) & set(available_amis_oss_arm))
    for index in range(len(no_rhel_oss)):
        result[f"NO_RHEL_OS_X86_{index}"] = no_rhel_oss_x86[(today_number + index) % len(no_rhel_oss_x86)]
        result[f"NO_RHEL_OS_ARM_{index}"] = no_rhel_oss_arm[(today_number + index) % len(no_rhel_oss_arm)]

    no_rocky_oss = [os for os in SUPPORTED_OSES if "rocky" not in os]
    no_rocky_oss_x86 = list(set(no_rocky_oss) & set(available_amis_oss_x86))
    no_rocky_oss_arm = list(set(no_rocky_oss) & set(available_amis_oss_arm))
    for index in range(len(no_rocky_oss)):
        result[f"NO_ROCKY_OS_X86_{index}"] = no_rocky_oss_x86[(today_number + index) % len(no_rocky_oss_x86)]
        result[f"NO_ROCKY_OS_ARM_{index}"] = no_rocky_oss_arm[(today_number + index) % len(no_rocky_oss_arm)]
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
                        if (
                            instance_type.get("GpuInfo").get("Gpus")
                            and instance_type.get("GpuInfo").get("Gpus")[0].get("Manufacturer") == "NVIDIA"
                        ):
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
    os_parameters = _get_os_parameters(config=config, args=args)
    instance_type_parameters = _get_instance_type_parameters()
    rendered_config = _render_config_file(
        config_file,
        **kwargs,
        **os_parameters,
        **instance_type_parameters,
        **_check_or_create_capacity_reservations(config_file, os_parameters, instance_type_parameters),
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


def _get_all_jinja_variables(config_file):
    """Get all jinja variables from config file."""
    config_dir = os.path.dirname(config_file)
    config_name = os.path.basename(config_file)
    file_loader = FileSystemLoader(config_dir)
    env = SandboxedEnvironment(loader=file_loader)
    template_source = env.loader.get_source(env, config_name)[0]
    parsed_content = env.parse(template_source)
    return meta.find_undeclared_variables(parsed_content)


def _check_or_create_capacity_reservations(config_file, os_parameters, instance_type_parameters):
    """Check/Create capacity reservations for all the instances in the config file."""
    variables = _get_all_jinja_variables(config_file)
    az_for_capacity_reservation = {}
    for var in variables:
        if "CAPACITY_RESERVATION" in var:
            logging.info("Checking capacity reservation for %s", var)
            count, enable_placement_group, hours, instance_type, os = _parse_capacity_reservation_variable(var)
            instance_type, os_platform = _resolve_instance_type_and_os(
                instance_type, instance_type_parameters, os, os_parameters
            )
            end_date = datetime.now(timezone.utc) + timedelta(hours=hours)
            candidate_regions = ["us-east-1", "us-west-2", "eu-west-1"]
            if _find_and_modify_existing_capacity_reservation(
                az_for_capacity_reservation, candidate_regions, count, end_date, instance_type, var, os_platform
            ):
                continue
            capacity_reservation_created = False
            try:
                for region in candidate_regions:
                    ec2_client = boto3.client("ec2", region_name=region)
                    capacity_reservation_created = _create_capacity_reservation(
                        az_for_capacity_reservation,
                        count,
                        ec2_client,
                        end_date,
                        instance_type,
                        var,
                        os_platform,
                        enable_placement_group,
                    )
                    if capacity_reservation_created:
                        break
            except Exception:
                az_for_capacity_reservation[var] = "use1-az6"
            if not capacity_reservation_created:
                # Assign arbitrary zone if no reservations can be made
                az_for_capacity_reservation[var] = "use1-az6"
    return az_for_capacity_reservation


def _resolve_instance_type_and_os(instance_type, instance_type_parameters, os, os_parameters):
    if "INSTANCE_TYPE" in instance_type:
        instance_type_size = instance_type.split("_")[-1]
        instance_type = (
            instance_type_parameters.get(instance_type[: -len(instance_type_size) - 1]) + "." + instance_type_size
        )
    else:
        instance_type = instance_type.replace("_", ".")
    os_platform = "Linux/UNIX"
    if os is not None:
        if "OS" in os:
            os = os_parameters.get(os)
        if "rhel" in os.lower():
            os_platform = "Red Hat Enterprise Linux"
    return instance_type, os_platform


def _parse_capacity_reservation_variable(var):
    # Example variable:
    # With rotating instance type and os:
    # {{ US_EAST_1_INSTANCE_TYPE_0_xlarge_CAPACITY_RESERVATION_2_INSTANCES_2_HOURS_NOPG_OS_X86_1 }}
    # With hardcode instance type and os:
    # {{ trn1_32xlarge_CAPACITY_RESERVATION_2_INSTANCES_2_HOURS_YESPG_UBUNTU2404 }}
    pattern = re.compile("(.*)_CAPACITY_RESERVATION_(.*)_INSTANCES_(.*)_HOURS_?(.*PG)?_?(.*)?")
    match = pattern.match(var)
    instance_type = match.group(1)
    count = int(match.group(2))
    hours = int(match.group(3))
    enable_placement_group = match.group(4) in ["YESPG", None]
    os = match.group(5) or "alinux2023"
    return count, enable_placement_group, hours, instance_type, os


def _create_capacity_reservation(
    az_for_capacity_reservation, count, ec2_client, end_date, instance_type, var, os_platform, enable_placement_group
):
    capacity_reservation_created = False
    for availability_zone in ec2_client.describe_availability_zones()["AvailabilityZones"]:
        if availability_zone["ZoneType"] == "availability-zone":
            try:
                zone_id = availability_zone["ZoneId"]
                reservation_args = {
                    "InstanceType": instance_type,
                    "InstancePlatform": os_platform,
                    "AvailabilityZoneId": zone_id,
                    "InstanceCount": count,
                    "EndDateType": "limited",
                    "EndDate": end_date,
                    "Tenancy": "default",
                }
                if enable_placement_group:
                    placement_group_name = f"{instance_type}_placement_group_{zone_id}"
                    try:
                        placement_group_arn = ec2_client.describe_placement_groups(GroupNames=[placement_group_name])[
                            "PlacementGroups"
                        ][0]["GroupArn"]
                    except Exception:
                        placement_group_arn = ec2_client.create_placement_group(
                            GroupName=placement_group_name, Strategy="cluster"
                        )["PlacementGroup"]["GroupArn"]
                    reservation_args["PlacementGroupArn"] = placement_group_arn
                ec2_client.create_capacity_reservation(**reservation_args)
                logging.info(
                    "Capacity reservation for %s %s on %s created in %s", count, instance_type, os_platform, zone_id
                )
                capacity_reservation_created = True
                az_for_capacity_reservation[var] = zone_id
                break
            except Exception as e:
                logging.info(
                    "Capacity reservation for %s %s failed to create in %s",
                    count,
                    instance_type,
                    zone_id,
                )
                logging.info(e)
    return capacity_reservation_created


def _find_and_modify_existing_capacity_reservation(  # noqa: C901
    az_for_capacity_reservation, candidate_regions, count, end_date, instance_type, var, os_platform
):
    """Find existing capacity reservation. Modify the reservation if more capacity or time is needed."""
    found_existing_capacity_reservation = False
    for region in candidate_regions:
        logging.info(
            "Checking existing capacity reservations for %s %s on %s in %s", count, instance_type, os_platform, region
        )
        try:
            ec2_client = boto3.client("ec2", region_name=region)
            paginator = ec2_client.get_paginator("describe_capacity_reservations")
            page_iterator = paginator.paginate(
                Filters=[
                    {"Name": "instance-type", "Values": [instance_type]},
                    {"Name": "state", "Values": ["active", "pending"]},
                    {"Name": "instance-platform", "Values": [os_platform]},
                ]
            )
            for page in page_iterator:
                for capacity_reservation in page["CapacityReservations"]:
                    if capacity_reservation["TotalInstanceCount"] >= count and (
                        capacity_reservation["EndDateType"] == "unlimited" or capacity_reservation["EndDate"] > end_date
                    ):
                        az_for_capacity_reservation[var] = capacity_reservation["AvailabilityZoneId"]
                        found_existing_capacity_reservation = True
                        logging.info(
                            "Found existing capacity reservation for %s %s in %s",
                            count,
                            instance_type,
                            capacity_reservation["AvailabilityZoneId"],
                        )
                        break
                    else:
                        logging.info(
                            "Found existing capacity reservation for %s %s in %s. "
                            "Modifing the capacity reservation for more instances/time",
                            count,
                            instance_type,
                            capacity_reservation["AvailabilityZoneId"],
                        )
                        try:
                            if capacity_reservation["EndDateType"] == "unlimited":
                                new_end_date = None
                            else:
                                new_end_date = (
                                    end_date
                                    if end_date > capacity_reservation["EndDate"]
                                    else capacity_reservation["EndDate"]
                                )
                            ec2_client.modify_capacity_reservation(
                                CapacityReservationId=capacity_reservation["CapacityReservationId"],
                                EndDate=new_end_date,
                                EndDateType=capacity_reservation["EndDateType"],
                                InstanceCount=max(count, capacity_reservation["TotalInstanceCount"]),
                            )
                            az_for_capacity_reservation[var] = capacity_reservation["AvailabilityZoneId"]
                            found_existing_capacity_reservation = True
                            logging.info(
                                "Modified capacity reservation for %s %s in %s",
                                count,
                                instance_type,
                                capacity_reservation["AvailabilityZoneId"],
                            )
                            break
                        except Exception as e:
                            logging.info("Failed to modify capacity reservation %s", e)
            if found_existing_capacity_reservation:
                break
        except Exception as e:
            logging.info("Failed to find existing capacity reservation %s", e)
    return found_existing_capacity_reservation
