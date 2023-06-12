#!/bin/bash
# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
slurm_plugin_path=$(sudo find / -iname slurm_plugin -print0|grep -FzZ 'node_virtualenv')
cat > $slurm_plugin_path/overrides.py << EOF
from botocore.exceptions import ClientError
import boto3


def run_instances(region, boto3_config, **run_instances_kwargs):
    if "ice-compute-resource" in run_instances_kwargs.get("LaunchTemplate", {}).get("LaunchTemplateName"):

        raise ClientError(
            {
                "Error": {
                    "Code": "InsufficientInstanceCapacity",
                    "Message": "Test InsufficientInstanceCapacity when calling the RunInstances operation.",
                },
                "ResponseMetadata": {"RequestId": "testid-123"},
            },
            "RunInstances",
        )
    else:
        ec2_client = boto3.client("ec2", region_name=region, config=boto3_config)
        return ec2_client.run_instances(**run_instances_kwargs)


def create_fleet(region, boto3_config, **create_fleet_kwargs):
    configs = create_fleet_kwargs.get("LaunchTemplateConfigs", [])
    if len(configs) >= 1 and configs[0]:
        lt_spec = configs.get("LaunchTemplateConfigs", [])[0].get("LaunchTemplateSpecification")
        if "ice-cr-multiple" in lt_spec.get("LaunchTemplateName"):
            response = {
                "Instances": [],
                "Errors": [
                    {"ErrorCode": "InsufficientInstanceCapacity", "ErrorMessage": "Insufficient capacity."},
                    {"ErrorCode": "InvalidParameterValue", "ErrorMessage": "We couldn't find any instance pools"
                     " that match your instance requirements. Change your instance requirements, and try again."}
                ],
                "ResponseMetadata": {"RequestId": "1234-abcde"},
            }

            return response
        else:
            ec2_client = boto3.client("ec2", region_name=region, config=boto3_config)
            return ec2_client.create_fleet(**create_fleet_kwargs)
    else:
        raise Exception("Missing LaunchTemplateSpecification parameter in create_fleet request.")
EOF
