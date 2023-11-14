#!/bin/bash
# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
set -ex

capacity_reservation_id=$1
capacity_reservation_override_file="/tmp/capacity-reservations-data.json"

# Write mocked output in a file to be able to modify it without the need to reload the python module
cat << EOF | sudo tee -a ${capacity_reservation_override_file}
{
    "CapacityReservationId": "${capacity_reservation_id}",
    "OwnerId": "447714826191",
    "CapacityReservationArn": "arn:aws:ec2:us-east-2:447714826191:capacity-reservation/${capacity_reservation_id}",
    "AvailabilityZoneId": "use2-az1",
    "InstanceType": "t2.micro",
    "InstancePlatform": "Linux/UNIX",
    "AvailabilityZone": "us-east-2a",
    "Tenancy": "default",
    "TotalInstanceCount": "0",
    "AvailableInstanceCount": "0",
    "EbsOptimized": "false",
    "EphemeralStorage": "false",
    "State": "pending",
    "StartDate": "2023-11-20T11:30:00+00:00",
    "EndDate": "2023-11-21T11:30:00+00:00",
    "EndDateType": "limited",
    "InstanceMatchCriteria": "targeted",
    "CreateDate": "2023-11-06T12:03:21+00:00",
    "Tags": [
        {
            "Key": "aws:ec2capacityreservation:incrementalRequestedQuantity",
            "Value": "4"
        },
        {
            "Key": "aws:ec2capacityreservation:capacityReservationType",
            "Value": "capacity-block"
        }
    ],
    "CapacityAllocations": [],
    "ReservationType": "capacity-block"
}
EOF


node_virtualenv_path=$(sudo find / -iname "site-packages" | grep "node_virtualenv")
# the overrides.py file must be in the same folder of the module of the function to be mocked
cat << EOF | sudo tee -a "${node_virtualenv_path}/aws/overrides.py"
import json
from aws.ec2 import CapacityReservationInfo

def describe_capacity_reservations(_, capacity_reservations_ids):
    capacity_reservation_data = {}
    # read content from a file, to be able to modify it without the need to reload clustermgtd python module
    with open("${capacity_reservation_override_file}") as override_file:
        capacity_reservation_data = json.load(override_file)
    return [CapacityReservationInfo(capacity_reservation_data)]
EOF

# create a fake fleet-config.json with a capacity block
cat << EOF | sudo tee "/etc/parallelcluster/slurm_plugin/fleet-config.json"
{
    "queue1": {
        "cr1": {
            "CapacityType": "capacity-block",
            "CapacityReservationId": "${capacity_reservation_id}",
            "Api": "run-instances",
            "Instances": [
                {
                    "InstanceType": "t2.micro"
                }
            ]
        }
    }
}
EOF
