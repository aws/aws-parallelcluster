# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from datetime import datetime, timedelta, timezone

import boto3
from utils import get_instance_info, get_similar_instance_types


def _find_existing_reservation(ec2_client, instance_type, az_id, instance_platform, with_placement_group):
    """Return True if an active capacity reservation already exists."""
    try:
        reservations = ec2_client.describe_capacity_reservations(
            Filters=[
                {"Name": "instance-type", "Values": [instance_type]},
                {"Name": "state", "Values": ["active"]},
            ]
        )["CapacityReservations"]
    except Exception as e:
        logging.warning("Could not list existing capacity reservations for %s: %s", instance_type, e)
        return False

    for reservation in reservations:
        if (
            reservation.get("AvailabilityZoneId") == az_id
            and reservation.get("InstancePlatform") == instance_platform
            and bool(reservation.get("PlacementGroupArn")) == with_placement_group
        ):
            logging.info(
                "Reusing existing capacity reservation %s for %s in %s (placement_group=%s)",
                reservation.get("CapacityReservationId"),
                instance_type,
                az_id,
                with_placement_group,
            )
            return True
    return False


def get_efa_instance_types(region, architecture):
    """Return EFA-capable instance types."""
    ec2_client = boto3.client("ec2", region_name=region)
    paginator = ec2_client.get_paginator("describe_instance_types")

    efa_instances = []
    for page in paginator.paginate(
        Filters=[
            {"Name": "network-info.efa-supported", "Values": ["true"]},
            {"Name": "supported-usage-class", "Values": ["on-demand", "spot"]},
            {"Name": "processor-info.supported-architecture", "Values": [architecture]},
        ],
    ):
        for instance in page["InstanceTypes"]:
            vcpus = instance.get("VCpuInfo", {}).get("DefaultVCpus", 0)
            efa_instances.append((vcpus, instance["InstanceType"]))

    # Primary sort by vCPU count (cost), secondary sort by name (determinism).
    efa_instances.sort(key=lambda item: (item[0], item[1]))

    instance_types = [instance_type for _, instance_type in efa_instances]
    logging.info("Retrieved %d EFA-capable instance types in %s: %s", len(instance_types), region, instance_types)
    return instance_types


def _ensure_cluster_placement_group(ec2_client, name):
    """Return the ARN of cluster placement group *name*, creating it if it does not exist."""
    try:
        return ec2_client.describe_placement_groups(GroupNames=[name])["PlacementGroups"][0]["GroupArn"]
    except Exception:
        return ec2_client.create_placement_group(GroupName=name, Strategy="cluster")["PlacementGroup"]["GroupArn"]


def resolve_instance_with_capacity(
    region, az_id, instance_type, os, minutes=50, count=2, alternative_instance_types=()
):
    """Reserve capacity for *instance_type* in *az_id*, falling back to similar instance types.

    A reservation is attempted for every instance type. For instances larger than ``.xlarge``
    (more than 4 vCPUs) an existing matching reservation is reused when present,
    avoiding duplicate reservations of expensive capacity; smaller types skip that check
    (small reservations shouldn't dedup because multiple tests use the same instance types).

    EFA-capable instances are reserved with a placement group.
    Non-EFA instances are reserved without a placement group.

    Returns the (possibly substituted) instance type string.
    """
    alternative_instance_types = alternative_instance_types or get_similar_instance_types(instance_type)
    candidates = [instance_type] + alternative_instance_types

    ec2_client = boto3.client("ec2", region_name=region)
    instance_info = get_instance_info(instance_type, region)
    vcpus = instance_info.get("VCpuInfo", {}).get("DefaultVCpus", 0)
    with_placement_group = instance_info.get("NetworkInfo", {}).get("EfaSupported", False)
    dedup = vcpus > 4
    instance_platform = "Red Hat Enterprise Linux" if "rhel" in os else "Linux/UNIX"
    end_date = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    for candidate in candidates:
        # For instances larger than .xlarge, reuse an existing reservation (dedup) before creating one.
        if dedup and _find_existing_reservation(ec2_client, candidate, az_id, instance_platform, with_placement_group):
            return candidate
        try:
            reservation_args = {
                "InstanceType": candidate,
                "InstancePlatform": instance_platform,
                "AvailabilityZoneId": az_id,
                "InstanceCount": count,
                "EndDateType": "limited",
                "EndDate": end_date,
                "Tenancy": "default",
            }
            if with_placement_group:
                placement_group_name = f"{candidate}_placement_group_{az_id}"
                reservation_args["PlacementGroupArn"] = _ensure_cluster_placement_group(
                    ec2_client, placement_group_name
                )
            cr_id = ec2_client.create_capacity_reservation(**reservation_args)["CapacityReservation"][
                "CapacityReservationId"
            ]
            logging.info(
                "Capacity reservation %s created for %s (count=%d) in %s " "(placement_group=%s, expires in %d min)",
                cr_id,
                candidate,
                count,
                az_id,
                with_placement_group,
                minutes,
            )
            return candidate
        except Exception as e:
            logging.warning("No capacity for %s in %s: %s", candidate, az_id, e)

    # Every candidate failed — return the original so the test gets a clear ICE error.
    logging.error(
        "Could not reserve capacity for any fallback instance type in %s/%s. "
        "Proceeding with %s (expect InsufficientInstanceCapacity).",
        region,
        az_id,
        instance_type,
    )
    return instance_type
