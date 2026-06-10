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
from utils import get_similar_instance_types

# Default instance types that are subject to capacity fallback.
DEFAULT_INSTANCE_TYPES = {"c5.xlarge", "m6g.xlarge", "m6i.xlarge"}


def resolve_instance_with_capacity(region, az_id, instance_type, os, minutes=50, count=2):
    """Try to reserve capacity for *instance_type* in *az_id*, falling back to alternatives on ICE.

    Only activates when *instance_type* is one of the known defaults (c5.xlarge / m6g.xlarge).
    For any other instance type the value is returned unchanged.

    The probe uses ``create_capacity_reservation`` — the same proven pattern used by
    ``_try_reserve_head_node_instance`` in test_efa.py.  A successful reservation
    guarantees capacity for the subsequent cluster launch and auto-expires after
    *minutes* minutes.

    Returns the (possibly substituted) instance type string.
    """
    if instance_type not in DEFAULT_INSTANCE_TYPES:
        return instance_type

    candidates = [instance_type] + get_similar_instance_types(instance_type)

    ec2_client = boto3.client("ec2", region_name=region)
    instance_platform = "Red Hat Enterprise Linux" if "rhel" in os else "Linux/UNIX"
    end_date = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    for candidate in candidates:
        try:
            response = ec2_client.create_capacity_reservation(
                InstanceType=candidate,
                InstancePlatform=instance_platform,
                AvailabilityZoneId=az_id,
                InstanceCount=count,
                EndDateType="limited",
                EndDate=end_date,
                Tenancy="default",
            )
            cr_id = response["CapacityReservation"]["CapacityReservationId"]
            logging.info(
                "Capacity reservation %s created for %s (count=%d) in %s (expires in %d min)",
                cr_id,
                candidate,
                count,
                az_id,
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
