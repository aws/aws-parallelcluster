# TODO Remove after batch launches CloudFormation Support
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
from __future__ import print_function
from __future__ import absolute_import
from builtins import str
import sys
import time
import logging
import boto3
import os
import json
from botocore.exceptions import ClientError

logger = logging.getLogger('cfncluster.cfncluster')

def create_client(config):
    return boto3.client('batch-zeta',
                         endpoint_url=config.batch_parameters.get('zeta_endpoint'),
                         region_name=config.region,
                         aws_access_key_id=config.aws_access_key_id,
                         aws_secret_access_key=config.aws_secret_access_key)

def poll_on_ce_status(batch, name):
    status = batch.describe_compute_environments(computeEnvironments=[name]) \
        .get('computeEnvironments')[0] \
        .get('status')

    while not status == 'VALID':
        logger.info("Waiting for Compute Environment %s to go from %s to VALID" % (name, status))
        time.sleep(5)
        status = batch.describe_compute_environments(computeEnvironments=[name]) \
            .get('computeEnvironments')[0] \
            .get('status')

def poll_on_jq_status(batch, name):
    status = batch.describe_job_queues(jobQueues=[name]) \
        .get('jobQueues')[0] \
        .get('status')

    while not status == 'VALID':
        logger.info("Waiting for Job Queue %s to go from %s to VALID" % (name, status))
        time.sleep(5)
        status = batch.describe_job_queues(jobQueues=[name]) \
            .get('jobQueues')[0] \
            .get('status')

def create_compute_environment(config, args):
    name = "cfncluster-%s-mnp" % args.cluster_name
    batch = create_client(config)

    # Check if Compute Environment exists
    try:
        ce = batch.describe_compute_environments(computeEnvironments=[name]) \
            .get('computeEnvironments')[0]
        return ce.get("computeEnvironmentArn") if ce.get('status') == 'VALID' else poll_on_ce_status(batch, name)
    except IndexError:
        pass

    try:
        max_nodes = int(config.parameters.get('MaxQueueSize')) if config.parameters.get('MaxQueueSize') else 10
    except ValueError:
        logger.error("Unable to convert max_queue_size = %s to a int." % config.parameters.get('MaxQueueSize'))
        sys.exit(1)

    response = batch.create_compute_environment(
        computeEnvironmentName = name,
        type = 'MANAGED',
        state = 'ENABLED',
        computeResources={
            'type': 'EC2',
            'minvCpus': int(config.parameters.get('MinvCpus')),
            'desiredvCpus': int(config.parameters.get('DesiredvCpus')),
            'maxvCpus': int(config.parameters.get('MaxvCpus')),
            'instanceTypes': config.parameters.get('ComputeInstanceType').split(', '),
            'subnets': [config.parameters.get('MasterSubnetId')],
            'securityGroupIds': [config.batch_parameters.get('security_group')],
            'ec2KeyPair': config.parameters.get('KeyName'),
            'instanceRole': config.batch_parameters.get('instance_role')
        },
        serviceRole=config.batch_parameters.get('service_role')
    )

    poll_on_ce_status(batch, response.get("computeEnvironmentName"))

    return response.get("computeEnvironmentArn")

def create_job_queue(config, args, compute_environment_arn):
    name = "cfncluster-%s-mnp" % args.cluster_name
    batch = create_client(config)

    # Check if Job Queue exists
    try:
        jq = batch.describe_job_queues(jobQueues=[name]) \
            .get('jobQueues')[0]
        return jq.get("jobQueueArn") if jq.get('status') == 'VALID' else poll_on_jq_status(batch, name)
    except IndexError:
        pass

    response = batch.create_job_queue(
        jobQueueName = name,
        state = 'ENABLED',
        priority=1,
        computeEnvironmentOrder=[
            {
                'order': 1,
                'computeEnvironment': compute_environment_arn
            }
        ]
    )

    poll_on_jq_status(batch, name)

    return response.get("jobQueueArn")


def main(config, args):
    resources = {}

    compute_environment_arn = create_compute_environment(config, args)
    job_queue_arn = create_job_queue(config, args, compute_environment_arn)
    job_def_arn = create_job_definition(config, args)

    resources["AWSBatchMNPBase"] = compute_environment_arn.split(':compute-environment/')[0]
    resources["AWSBatchMNPName"] = compute_environment_arn.split(':compute-environment/')[1]

    return resources
