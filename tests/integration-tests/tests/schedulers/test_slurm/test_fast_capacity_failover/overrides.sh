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
EOF
