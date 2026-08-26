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
import random
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import boto3
import yaml
from botocore.exceptions import ClientError
from jinja2 import FileSystemLoader, meta
from jinja2.sandbox import SandboxedEnvironment
from utils import InstanceTypesData

from pcluster.constants import (
    SUPPORTED_OSES,
    UNSUPPORTED_ARM_OSES_FOR_DCV,
    UNSUPPORTED_OSES_FOR_DCV,
    UNSUPPORTED_OSES_FOR_LUSTRE,
)

UNSUPPORTED_OSES_FOR_NON_GPU_DCV = ["rocky9", "rhel9"]
EXCLUDED_INSTANCE_TYPE_PREFIXES = (
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
)
# An instant capacity block starts ~30 minutes after the request; allow some slack when telling
# instant offerings apart from standard ones (which start at the next 11:30 UTC boundary).
INSTANT_CAPACITY_BLOCK_START_MINUTES = 45

# Never buy more than the remainder of one capacity-block day: instant offerings can span several
# days (ending on a later 11:30 UTC boundary) and cost a multiple of what a test run needs.
MAX_CAPACITY_BLOCK_HOURS = 24

# Set this to render capacity block variables without looking for (or buying) any capacity. Config
# validation renders every file under configs/, and that must never spend money.
CAPACITY_BLOCK_DRY_RUN_ENV_VAR = "PCLUSTER_SKIP_CAPACITY_BLOCK_PURCHASE"


def _get_global_build_number(config=None, args=None):
    """
    Gets the global build number from args or pytest config.
    Returns the build number as an int, or 0 if not provided.
    """
    global_build_number = 0
    if args:
        args_dict = vars(args)
        global_build_number = args_dict.get("global_build_number", 0)
    elif config:
        global_build_number = config.getoption("--global-build-number", default=0)
    try:
        return int(global_build_number)
    except (TypeError, ValueError):
        return 0


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

    # Use global-build-number as the rotation seed if available and non-zero.
    # This allows the OS rotation to advance on every build, enabling full coverage
    # when running tests multiple times per day. Falls back to day-based rotation otherwise.
    global_build_number = _get_global_build_number(config=config, args=args)
    if global_build_number:
        rotation_seed = global_build_number
    else:
        rotation_seed = (date.today() - date(2020, 1, 1)).days

    _propagate_os_jinja_variables("", result, rotation_seed, SUPPORTED_OSES)

    # DCV doesn't support AL2023. Therefore, the following logic makes sure the DCV jinja parameter is not AL2023
    dcv_supported_oses = [
        os for os in SUPPORTED_OSES if os not in UNSUPPORTED_OSES_FOR_DCV + UNSUPPORTED_OSES_FOR_NON_GPU_DCV
    ]
    dcv_supported_arm_oses = [
        os
        for os in SUPPORTED_OSES
        if os not in UNSUPPORTED_OSES_FOR_DCV + UNSUPPORTED_ARM_OSES_FOR_DCV + UNSUPPORTED_OSES_FOR_NON_GPU_DCV
    ]
    _propagate_os_jinja_variables("DCV_", result, rotation_seed, dcv_supported_oses, dcv_supported_arm_oses)

    lustre_supported_oses = [os for os in SUPPORTED_OSES if os not in UNSUPPORTED_OSES_FOR_LUSTRE]
    _propagate_os_jinja_variables("LUSTRE_", result, rotation_seed, lustre_supported_oses)

    no_rhel_oss = [os for os in SUPPORTED_OSES if "rhel" not in os]
    _propagate_os_jinja_variables("NO_RHEL_", result, rotation_seed, no_rhel_oss)

    no_rocky_oss = [os for os in SUPPORTED_OSES if "rocky" not in os]
    _propagate_os_jinja_variables("NO_ROCKY_", result, rotation_seed, no_rocky_oss)

    rhel_oss = [os for os in SUPPORTED_OSES if "rhel" in os]
    _propagate_os_jinja_variables("RHEL_", result, rotation_seed, rhel_oss)

    ubuntu_oss = [os for os in SUPPORTED_OSES if "ubuntu" in os]
    _propagate_os_jinja_variables("UBUNTU_", result, rotation_seed, ubuntu_oss)
    return result


def _propagate_os_jinja_variables(prefix, result, rotation_seed, supported_x86_oses, supported_arm_oses=None):
    available_amis_oss_x86 = result["AVAILABLE_AMIS_OSS_X86"]
    available_amis_oss_arm = result["AVAILABLE_AMIS_OSS_ARM"]
    if supported_arm_oses is None:
        supported_arm_oses = supported_x86_oses
    # The OS list is the intersection of supported OSes and available AMIs.
    # If the intersection is empty, fallback to supported OS to prevent the framework from failing of div by 0
    available_amis_oss_x86 = sorted(list(set(supported_x86_oses) & set(available_amis_oss_x86))) or supported_x86_oses
    available_amis_oss_arm = sorted(list(set(supported_arm_oses) & set(available_amis_oss_arm))) or supported_arm_oses
    result[f"{prefix}OS_X86"] = available_amis_oss_x86
    result[f"{prefix}OS_ARM"] = available_amis_oss_arm
    for index in range(len(supported_x86_oses)):
        result[f"{prefix}OS_X86_{index}"] = available_amis_oss_x86[
            (rotation_seed + index) % len(available_amis_oss_x86)
        ]
        result[f"{prefix}OS_ARM_{index}"] = available_amis_oss_arm[
            (rotation_seed + index) % len(available_amis_oss_arm)
        ]


def _get_instance_type_parameters():  # noqa: C901
    """Gets Instance jinja parameters."""
    # Return cached result if available
    if hasattr(_get_instance_type_parameters, "_cache"):
        return _get_instance_type_parameters._cache

    result = {}

    for region in ["us-east-1", "us-west-2"]:  # Only populate instance type for big regions
        ec2_client = boto3.client("ec2", region_name=region)
        # The following conversion is required becase Python jinja doesn't like "-"
        region_jinja = region.replace("-", "_").upper()
        try:
            xlarge_instances = set()
            all_gpu_instances = set()
            instance_type_availability_zones = defaultdict(list)
            # Get instance type offerings and build AZ mapping
            paginator = ec2_client.get_paginator("describe_instance_type_offerings")

            for page in paginator.paginate(LocationType="availability-zone"):
                for offering in page["InstanceTypeOfferings"]:
                    instance_type_name = offering["InstanceType"]
                    instance_type_availability_zones[instance_type_name].append(offering["Location"])
                    # Check if instance type ends with '.xlarge'
                    if instance_type_name.endswith(".xlarge") and _is_current_instance_type_generation(
                        EXCLUDED_INSTANCE_TYPE_PREFIXES, offering
                    ):
                        xlarge_instances.add(instance_type_name)
                    # Get a list of only GPU instances of any size available in the region
                    if (
                        instance_type_name.startswith("p") or instance_type_name.startswith("g")
                    ) and _is_current_instance_type_generation(EXCLUDED_INSTANCE_TYPE_PREFIXES, offering):
                        all_gpu_instances.add(instance_type_name)

            # Get GPU instance details in batches of 100
            all_gpu_list = list(all_gpu_instances)
            gpu_instances = []
            fractional_gpu_instances = set()
            paginator = ec2_client.get_paginator("describe_instance_types")
            # DescribeInstanceType API Limit of 100 instances
            batch_size = 100

            for i in range(0, len(all_gpu_list), batch_size):
                gpu_instance_type_batch = all_gpu_list[i : i + batch_size]  # noqa: E203
                for page in paginator.paginate(InstanceTypes=gpu_instance_type_batch):
                    for instance_type in page["InstanceTypes"]:
                        if _is_fractional_gpu_instance_type(instance_type):
                            fractional_gpu_instances.add(instance_type["InstanceType"])
                            continue
                        if _is_nvidia_gpu_instance_type(instance_type):
                            if instance_type.get("GpuInfo").get("Gpus")[0].get(
                                "Count"
                            ) >= 4 and _is_current_instance_type_generation(
                                EXCLUDED_INSTANCE_TYPE_PREFIXES, instance_type
                            ):
                                # Find instance types with 4 or more GPUs. Number of GPUs can change test behavior.
                                # For example, it takes longer for DCGM health check to diagnose multiple GPUs.
                                instance_size = instance_type["InstanceType"].split(".")[1][: -len("xlarge")]
                                if instance_size and int(instance_size) < 20:
                                    # Avoid using very expensive instance types
                                    gpu_instances.append(instance_type["InstanceType"])
                            else:
                                gpu_instances.append(instance_type["InstanceType"])

            xlarge_instances -= fractional_gpu_instances

            xlarge_sorted = sorted(xlarge_instances)
            gpu_sorted = sorted(gpu_instances)

            logging.info(f"Selected .xlarge instance types: {xlarge_sorted}")
            logging.info(f"Selected GPU instance types: {gpu_sorted}")

            today_number = (date.today() - date(2020, 1, 1)).days
            for index, _ in enumerate(xlarge_sorted):
                instance_type = xlarge_sorted[(today_number + index) % len(xlarge_sorted)]
                azs = instance_type_availability_zones[instance_type]
                result[f"{region_jinja}_INSTANCE_TYPE_{index}"] = instance_type[: -len(".xlarge")]
                result[f"{region_jinja}_INSTANCE_TYPE_{index}_AZ"] = azs[0] if len(azs) <= 2 else region

            for index, _ in enumerate(gpu_sorted):
                instance_type = gpu_sorted[(today_number + index) % len(gpu_sorted)]
                azs = instance_type_availability_zones[instance_type]
                result[f"{region_jinja}_GPU_INSTANCE_TYPE_{index}"] = instance_type
                result[f"{region_jinja}_GPU_INSTANCE_TYPE_{index}_AZ"] = azs[0] if len(azs) <= 2 else region

        except Exception as e:
            print(f"Error getting instance types: {str(e)}. Using c5 and g4dn as the default instance type")
            for index in range(100):
                result[f"{region_jinja}_INSTANCE_TYPE_{index}"] = "c5"
                result[f"{region_jinja}_INSTANCE_TYPE_{index}_AZ"] = region
            for index in range(10):
                result[f"{region_jinja}_GPU_INSTANCE_TYPE_{index}"] = "g4dn.xlarge"
                result[f"{region_jinja}_GPU_INSTANCE_TYPE_{index}_AZ"] = region

    # Cache the result
    _get_instance_type_parameters._cache = result
    return result


def _is_nvidia_gpu_instance_type(instance_type):
    """
    Return True if the instance type exposes a full NVIDIA GPU.

    Fractional-GPU instances (e.g. g6f, gr6f) are filtered out.
    """
    gpu = next(iter((instance_type.get("GpuInfo") or {}).get("Gpus") or []), {})
    return gpu.get("Manufacturer") == "NVIDIA" and (gpu.get("Count") or 0) >= 1


def _is_fractional_gpu_instance_type(instance_type):
    """
    Return True if the instance type exposes a fractional NVIDIA GPU (e.g. g6f, gr6f).

    Fractional-GPU instances report an NVIDIA GPU in GpuInfo with a Count of 0 (a slice of a
    physical GPU), unlike full-GPU instances which report a Count of 1 or more.
    """
    gpu = next(iter((instance_type.get("GpuInfo") or {}).get("Gpus") or []), {})
    return gpu.get("Manufacturer") == "NVIDIA" and (gpu.get("Count") or 0) < 1


def _is_current_instance_type_generation(excluded_instance_type_prefixes, instance_type):
    return not any(instance_type["InstanceType"].startswith(prefix) for prefix in excluded_instance_type_prefixes)


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
        if "CAPACITY_BLOCK" in var:
            _check_or_buy_capacity_block(az_for_capacity_reservation, var, os_parameters, instance_type_parameters)
        elif "CAPACITY_RESERVATION" in var:
            logging.info("Checking capacity reservation for %s", var)
            specs = []
            for part in var.split("__"):  # Support multiple instance types separated by __
                count, enable_placement_group, hours, instance_type, os = _parse_capacity_reservation_variable(part)
                instance_type, os_platform = _resolve_instance_type_and_os(
                    instance_type, instance_type_parameters, os, os_parameters
                )
                end_date = datetime.now(timezone.utc) + timedelta(hours=hours)
                specs.append((instance_type, os_platform, count, end_date, enable_placement_group))
            candidate_regions = [
                "ap-northeast-2",
                "ap-southeast-2",
                "ap-northeast-1",
                "eu-north-1",
                "eu-west-2",
                "eu-west-1",
                "us-east-2",
                "us-west-2",
                "us-east-1",
            ]
            random.shuffle(candidate_regions)
            if not _create_capacity_reservations(az_for_capacity_reservation, candidate_regions, specs, var):
                # If failed to create reservation, use use1-az6 to avoid making the test yaml syntactically wrong.
                logging.info("Failed to create capacity reservation for %s. Using use1-az6", var)
                az_for_capacity_reservation[var] = "use1-az6"
    return az_for_capacity_reservation


def _check_or_buy_capacity_block(az_for_capacity_reservation, var, os_parameters, instance_type_parameters):
    """Resolve a ``*_CAPACITY_BLOCK_*`` variable to the AZ of a usable capacity block.

    Some instance types (notably the p6 family) can realistically only be obtained through capacity
    blocks. A block already owned is reused when it still covers the run; otherwise an "instant"
    block is bought, sweeping the candidate regions until one has an offering. The AZ of the block
    is what the variable renders to, so the test runs where the capacity actually is.

    Buying a capacity block is an upfront, non-refundable charge, hence only one is ever bought and
    only for variables explicitly declared as capacity blocks in the test config.

    Raises when no capacity block can be obtained in any candidate region.
    """
    logging.info("Checking capacity block for %s", var)
    count, hours, instance_type, os_name = _parse_capacity_block_variable(var)
    instance_type, os_platform = _resolve_instance_type_and_os(
        instance_type, instance_type_parameters, os_name, os_parameters
    )
    if os.environ.get(CAPACITY_BLOCK_DRY_RUN_ENV_VAR):
        # Config validation renders every file under configs/, which must not spend money. Render a
        # placeholder AZ just to keep the test yaml valid.
        logging.info("%s set: not looking for a capacity block for %s", CAPACITY_BLOCK_DRY_RUN_ENV_VAR, var)
        az_for_capacity_reservation[var] = "use1-az6"
        return
    # Regions where the capacity-block-only instance types (p6 family) are offered.
    candidate_regions = [
        "ap-south-1",
        "us-east-1",
        "us-east-2",
        "us-west-2",
    ]
    random.shuffle(candidate_regions)

    for region in candidate_regions:
        az_id = _find_or_buy_capacity_block(region, instance_type, os_platform, count, hours)
        if az_id:
            az_for_capacity_reservation[var] = az_id
            return
    # Tests declaring a capacity block are run on demand, so there is nothing to gain from carrying
    # on with a config that cannot possibly work: fail loudly instead of skipping later on.
    raise Exception(
        f"Could not find or buy a capacity block for {instance_type} ({os_platform}, {count} instances, "
        f">={hours}h) in any of {candidate_regions}. Capacity blocks are only sold until "
        "05:00 UTC for same-day use; retry within the selling window or pick another instance type."
    )


def _find_or_buy_capacity_block(region, instance_type, os_platform, count, min_hours):
    """Return the AZ ID of a capacity block usable in *region*, reusing or buying one, else None."""
    ec2_client = boto3.client("ec2", region_name=region)
    reservation = _find_usable_capacity_block(ec2_client, region, instance_type, os_platform, count)
    if reservation:
        return _wait_for_capacity_block_active(
            ec2_client, reservation["CapacityReservationId"], reservation["StartDate"], reservation["EndDate"]
        )
    return _buy_instant_capacity_block(ec2_client, region, instance_type, os_platform, count, min_hours)


def _find_usable_capacity_block(ec2_client, region, instance_type, os_platform, count):
    """Return an already-owned capacity block the tests can run on, or None.

    Such a block has been paid for already, so it is worth using no matter how little of it is left:
    at worst the tests run out of time, which is still better than buying a second block. A block
    bought ahead of time is still `scheduled` rather than `active`, and is taken as well: the caller
    waits for it to start. Its instance count is read from ``TotalInstanceCount``, because EC2 only
    reports instances as available once the block is active.
    """
    now = datetime.now(timezone.utc)
    try:
        for page in ec2_client.get_paginator("describe_capacity_reservations").paginate():
            for reservation in page.get("CapacityReservations", []):
                if (
                    reservation.get("ReservationType") == "capacity-block"
                    and reservation.get("InstanceType") == instance_type
                    and reservation.get("InstancePlatform") == os_platform
                    and reservation.get("State") in ("active", "scheduled")
                    and reservation.get("TotalInstanceCount", 0) >= count
                ):
                    end_date = reservation.get("EndDate")
                    remaining = (end_date - now).total_seconds() / 3600 if end_date else float("inf")
                    logging.info(
                        "Reusing %s capacity block %s for %s in %s (%.1fh remaining)",
                        reservation["State"],
                        reservation["CapacityReservationId"],
                        instance_type,
                        reservation.get("AvailabilityZoneId"),
                        remaining,
                    )
                    return reservation
    except Exception as e:
        logging.info("Could not list capacity reservations in %s: %s", region, e)
    return None


def _is_usable_instant_offering(offering, min_hours, instance_type, region):
    """Return True if *offering* is an instant block long enough for the run but no longer than a day."""
    starts_in = (offering["StartDate"] - datetime.now(timezone.utc)).total_seconds() / 60
    hours = (offering["EndDate"] - offering["StartDate"]).total_seconds() / 3600
    # A standard block starts at the next 11:30 UTC boundary, so it would be paid for now and only
    # become usable tomorrow.
    if starts_in > INSTANT_CAPACITY_BLOCK_START_MINUTES:
        return False
    # Instant offerings also come in multi-day flavours, ending on a later 11:30 UTC boundary. Those
    # cost a multiple of a single day for capacity the tests cannot use.
    if hours > MAX_CAPACITY_BLOCK_HOURS:
        logging.info(
            "Ignoring %.0fh capacity block offering %s (%s %s): longer than the %dh cap",
            hours,
            offering["CapacityBlockOfferingId"],
            instance_type,
            region,
            MAX_CAPACITY_BLOCK_HOURS,
        )
        return False
    return hours >= min_hours


def _buy_instant_capacity_block(ec2_client, region, instance_type, os_platform, count, min_hours):
    """Buy the cheapest instant capacity block covering *min_hours*, returning its AZ ID or None.

    Instant blocks start ~30 minutes from now and end at the next capacity-block day boundary
    (11:30 UTC), so their duration is whatever is left of the current block day and they are priced
    pro-rata. Picking the cheapest offering therefore buys the shortest block that still fits the
    run, which is what keeps the cost down.
    """
    # The API only accepts whole-day durations, but answers with the partial-day instant offerings
    # alongside the standard block, which is what we are after. Asking for a single day is enough:
    # an instant block always ends on a 11:30 UTC boundary, so asking for more days only adds
    # offerings longer than MAX_CAPACITY_BLOCK_HOURS.
    try:
        offerings = ec2_client.describe_capacity_block_offerings(
            InstanceType=instance_type, InstanceCount=count, CapacityDurationHours=MAX_CAPACITY_BLOCK_HOURS
        )["CapacityBlockOfferings"]
    except Exception as e:
        logging.info("No capacity block offerings for %s in %s: %s", instance_type, region, e)
        return None

    candidates = [
        (float(offering["UpfrontFee"]), offering)
        for offering in offerings
        if _is_usable_instant_offering(offering, min_hours, instance_type, region)
    ]
    if not candidates:
        logging.info(
            "No instant capacity block offering for %s (%d-%dh) in %s",
            instance_type,
            min_hours,
            MAX_CAPACITY_BLOCK_HOURS,
            region,
        )
        return None

    fee, offering = min(candidates, key=lambda item: item[0])
    try:
        reservation = ec2_client.purchase_capacity_block(
            CapacityBlockOfferingId=offering["CapacityBlockOfferingId"], InstancePlatform=os_platform
        )["CapacityReservation"]
    except ClientError as e:
        # EC2 rejected the purchase (expired offering, capacity taken meanwhile, ...): nothing was
        # charged, so another region can safely be tried.
        logging.warning("Failed to purchase capacity block %s: %s", offering["CapacityBlockOfferingId"], e)
        return None
    except Exception as e:
        # Anything else (timeout, connection reset) leaves the purchase in an unknown state: it may
        # well have gone through and been charged. Look for the reservation instead of buying again.
        logging.warning(
            "Purchase of capacity block %s in %s got no clear answer from EC2 (%s): checking whether it "
            "went through anyway",
            offering["CapacityBlockOfferingId"],
            region,
            e,
        )
        reservation = _find_usable_capacity_block(ec2_client, region, instance_type, os_platform, count)
        if reservation:
            return _wait_for_capacity_block_active(
                ec2_client, reservation["CapacityReservationId"], reservation["StartDate"], reservation["EndDate"]
            )
        # Nothing was charged after all, so the other regions can still be tried.
        logging.warning("Purchase of %s did not go through, moving on", offering["CapacityBlockOfferingId"])
        return None
    logging.info(
        "Purchased capacity block %s: %s x%d on %s in %s, %s -> %s, upfront fee %s %s",
        reservation["CapacityReservationId"],
        instance_type,
        count,
        os_platform,
        offering["AvailabilityZone"],
        offering["StartDate"],
        offering["EndDate"],
        fee,
        offering["CurrencyCode"],
    )
    return _wait_for_capacity_block_active(
        ec2_client, reservation["CapacityReservationId"], offering["StartDate"], offering["EndDate"]
    )


def _wait_for_capacity_block_active(ec2_client, reservation_id, start_date, end_date):
    """Block until the capacity block is active, then return its AZ ID.

    A freshly bought instant block only starts ~30 minutes later: until then it is `scheduled` and
    instances cannot be launched against it, so the tests have to wait for it here. The AZ is read
    back here too, since EC2 does not report one until the block has been allocated.

    The block is paid for whatever happens, so this keeps waiting for as long as the block exists:
    whatever time is left of it is worth attempting the tests with. The wait ends by itself because
    EC2 moves the reservation to `expired` once its end date passes.

    Raises if the block never becomes usable.
    """
    logging.info(
        "Waiting for capacity block %s to become active (starts at %s, expires at %s)",
        reservation_id,
        start_date,
        end_date,
    )
    while True:
        try:
            reservation = ec2_client.describe_capacity_reservations(CapacityReservationIds=[reservation_id])[
                "CapacityReservations"
            ][0]
        except Exception as e:
            # The reservation can briefly be unreadable right after purchase.
            logging.info("Could not read state of capacity block %s yet: %s", reservation_id, e)
            reservation = {"State": "unknown"}
        state = reservation["State"]
        if state == "active":
            az_id = reservation["AvailabilityZoneId"]
            logging.info("Capacity block %s is active in %s", reservation_id, az_id)
            return az_id
        if state in ("cancelled", "expired", "failed", "payment-failed"):
            raise Exception(
                f"Capacity block {reservation_id} reached unusable state {state} before the tests could "
                "run against it."
            )
        logging.info("Capacity block %s is %s, checking again in a minute", reservation_id, state)
        time.sleep(60)


def _parse_capacity_block_variable(var):
    # Example variable:
    # {{ p6_b200_48xlarge_CAPACITY_BLOCK_2_INSTANCES_6_HOURS_alinux2023 }}
    pattern = re.compile("(.*)_CAPACITY_BLOCK_(.*)_INSTANCES_(.*)_HOURS_?(.*)?")
    match = pattern.match(var)
    instance_type = match.group(1)
    count = int(match.group(2))
    hours = int(match.group(3))
    os = match.group(4) or "alinux2023"
    return count, hours, instance_type, os


def _create_capacity_reservations(az_for_cr, regions, specs, var):  # noqa C901
    """Find or create capacity reservations for multiple instance types in the same AZ."""
    for region in regions:
        try:
            ec2_client = boto3.client("ec2", region_name=region)
            for az in ec2_client.describe_availability_zones()["AvailabilityZones"]:
                if az["ZoneType"] != "availability-zone":
                    continue
                zone_id = az["ZoneId"]
                created_capacity_reservation_ids = []
                success = True
                for instance_type, os_platform, count, end_date, enable_placement_group in specs:
                    reservation_id = _create_single_capacity_reservation(
                        zone_id, count, ec2_client, end_date, instance_type, os_platform, enable_placement_group
                    )
                    if reservation_id:
                        created_capacity_reservation_ids.append(reservation_id)
                    else:
                        success = False
                        break
                if success:
                    az_for_cr[var] = zone_id
                    logging.info("Created reservations for all instance types in %s", zone_id)
                    return True
                for reservation_id in created_capacity_reservation_ids:
                    try:
                        logging.info(
                            "Some instance types cannot be reserved in %s, cancelling back reservation %s",
                            az,
                            reservation_id,
                        )
                        ec2_client.cancel_capacity_reservation(CapacityReservationId=reservation_id)
                    except Exception:
                        pass
        except Exception as e:
            logging.info("Failed creating reservations in %s: %s", region, e)
    return False


def _replace_last(string, old, new):
    """Replaces the last occurrence of a substring in a string."""
    parts = string.rsplit(old, 1)
    return new.join(parts)


def _resolve_instance_type_and_os(instance_type, instance_type_parameters, os, os_parameters):
    if "INSTANCE_TYPE" in instance_type:
        # The value of the Jinja INSTANCE_TYPE variable can contain a size or not, e.g. trn1.32xlarge vs trn1.
        # When Jinja name is like INSTANCE_TYPE_0_xlarge, the value doesn't contain size
        # When Jinja name is like INSTANCE_TYPE_0, the value contains size.
        # In other words, the size should appear once either in name or value. The code below handles this logic.
        instance_type_size = instance_type.split("_")[-1]
        instance_type_family = instance_type_parameters.get(instance_type[: -len(instance_type_size) - 1])
        if instance_type_family:
            instance_type = instance_type_family + "." + instance_type_size
        else:
            instance_type = instance_type_parameters.get(instance_type)
    else:
        instance_type = _replace_last(instance_type, "_", ".")
        instance_type = instance_type.replace("_", "-")
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


def _create_single_capacity_reservation(
    zone_id, count, ec2_client, end_date, instance_type, os_platform, enable_placement_group
):
    try:
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
        reservation_id = ec2_client.create_capacity_reservation(**reservation_args)["CapacityReservation"][
            "CapacityReservationId"
        ]
        logging.info("Capacity reservation for %s %s on %s created in %s", count, instance_type, os_platform, zone_id)
        return reservation_id
    except Exception as e:
        logging.info(
            "Capacity reservation for %s %s failed to create in %s",
            count,
            instance_type,
            zone_id,
        )
        logging.info(e)
        return None
