from __future__ import print_function
from __future__ import absolute_import
# Copyright 2013-2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with the
# License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from builtins import str
import sys
import time
import logging
import boto3
import os
import json
from botocore.exceptions import ClientError

logger = logging.getLogger('cfncluster.cfncluster')

ZETA_ENDPOINT = 'https://zeta.us-east-1.dilithium.aws.a2z.com'
DOCKER_IMAGE = '822857487308.dkr.ecr.us-east-1.amazonaws.com/cfncluster-alinux'
JOB_ROLE_ARN = 'arn:aws:iam::822857487308:role/ecsInstanceRole'

def get_config_parameter(config, param, default):
    items = [i[1] for i in config.parameters if i[0] == param]

    if items != []:
        return items[0]

    return default

def create_client(config):
    return boto3.client('batch-zeta',
                         endpoint_url=ZETA_ENDPOINT,
                         region_name=config.region,
                         aws_access_key_id=config.aws_access_key_id,
                         aws_secret_access_key=config.aws_secret_access_key)


def create_job_definition(config, args):

    batch = create_client(config)

    try:
        max_nodes = int(get_config_parameter(config, param='MaxQueueSize', default=10))
    except ValueError:
        logger.error("Unable to convert max_queue_size = %s to a int." % get_config_parameter(config, param='MaxQueueSize', default=10))
        sys.exit(1)

    response = batch.register_job_definition(
        jobDefinitionName="%s-mnp" % args.cluster_name,
        type='multinode',
        nodeProperties = {
            "numNodes": max_nodes,
            "mainNode": 0,
            "nodeRangeProperties": [
                {
                    "targetNodes": "0:%d" % (max_nodes - 1),
                    "container": {
                        "image": DOCKER_IMAGE,
                        'jobRoleArn': JOB_ROLE_ARN,
                        "memory": 123,
                        "mountPoints": [],
                        "ulimits": [],
                        'privileged': True,
                        'user': 'root',
                        "vcpus": 1
                    }
                }
            ]
        }
    )

    return response.get("jobDefinitionName")
