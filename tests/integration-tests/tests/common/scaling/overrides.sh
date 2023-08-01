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
import logging

logger = logging.getLogger(__name__)

def run_instances(region, boto3_config, **run_instances_kwargs):
    if "ice-compute-resource" in run_instances_kwargs.get("LaunchTemplate", {}).get("LaunchTemplateName"):
        # Forcing the Placement/tenancy override to host will trigger an InsufficientHostCapacity since we do not
        # have a fleet of reserved hosts
        run_instances_kwargs['Placement']= {'Tenancy': 'host'}
        logger.info("Updated parameters for EC2 run_instances: %s", run_instances_kwargs)
    ec2_client = boto3.client("ec2", region_name=region, config=boto3_config)
    return ec2_client.run_instances(**run_instances_kwargs)

def update_lt_instance_overrides(overrides):
    updated_overrides = []
    for ov in overrides:
        if 'InstanceType' in ov:
            # mutate t2.large into t2-large to force an Error in CreateFleet request
            mispelled_instance_type = ov['InstanceType'].replace(".", "-")
            ov['InstanceType'] = mispelled_instance_type
            updated_overrides.append(ov)
        else:
            updated_overrides.append(ov)

    return updated_overrides

def create_fleet(region, boto3_config, **create_fleet_kwargs):
    configs = create_fleet_kwargs.get("LaunchTemplateConfigs", [])
    if len(configs) >= 1 and configs[0]:
        lt_config = configs[0]

        if "ice-cr-multiple" in lt_config.get('LaunchTemplateSpecification').get("LaunchTemplateName"):
            # CreateFleet will return an Error and an empty list of instances
            lt_config['Overrides'] = update_lt_instance_overrides(lt_config['Overrides'])
            logger.info("Updated Instance Overrides for CreateFleet args: %s", create_fleet_kwargs)
        elif "exception-cr-multiple" in lt_config.get('LaunchTemplateSpecification').get("LaunchTemplateName"):
            # force CreateFleet to raise an exception since `inf*` instance types have Inferentia accelerators
            # that are manufactured by AWS, and we are also requesting Manufacturer=nvidia
            lt_config['Overrides'] = [{
                        "InstanceRequirements": {
                            "VCpuCount": { "Min": 2 },
                            "MemoryMiB": { "Min": 2048 },
                            "AllowedInstanceTypes": [  "inf*" ],
                            "AcceleratorManufacturers": [ "nvidia" ]
                        }
                    }]
            logger.info("Updated Instance Overrides for CreateFleet args: %s", create_fleet_kwargs)

        ec2_client = boto3.client("ec2", region_name=region, config=boto3_config)
        return ec2_client.create_fleet(**create_fleet_kwargs)
    else:
        raise Exception("Missing LaunchTemplateSpecification parameter in create_fleet request.")
EOF
