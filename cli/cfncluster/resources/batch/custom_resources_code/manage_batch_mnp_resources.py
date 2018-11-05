# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with
#  the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import json
import os
import time

import boto3
from botocore.exceptions import ClientError

import crhelper

# initialise logger
logger = crhelper.log_config({"RequestId": "CONTAINER_INIT"}, loglevel='info')
logger.info('Logging configured')
# set global to track init failures
init_failed = False

try:
    # Place initialization code here
    # ToDo: remove after MNP launch
    logger.info("Configuring Batch ZStack")
    aws_data_path = os.environ.get('AWS_DATA_PATH', '').split(os.pathsep)
    aws_data_path.append(os.path.join(os.getcwd(), 'models'))
    os.environ.update({'AWS_DATA_PATH': os.pathsep.join(aws_data_path)})
    batch_client = boto3.client('batch-zeta', endpoint_url='https://zeta.us-east-1.dilithium.aws.a2z.com')
    logger.info("Container initialization completed")
except Exception as e:
    logger.error(e, exc_info=True)
    init_failed = e


# ToDo: remove after MNP launch --------
def poll_on_ce_status(name, desired_status='VALID'):
    status = ''
    while not status == desired_status:
        logger.info("Waiting for Compute Environment %s to go to %s" % (name, desired_status))
        time.sleep(5)
        status = batch_client.describe_compute_environments(computeEnvironments=[name]) \
            .get('computeEnvironments')[0] \
            .get('status')
    logger.info("Compute Environment status is VALID")


def poll_on_jq_status(name, desired_status='VALID'):
    status = ''
    while not status == desired_status:
        logger.info("Waiting for Job Queue %s to go to %s" % (name, desired_status))
        time.sleep(5)
        status = batch_client.describe_job_queues(jobQueues=[name]) \
            .get('jobQueues')[0] \
            .get('status')
    logger.info("Job Queue status is VALID")


def create_compute_environment(config):
    name = "%s-mnp" % config['ClusterName']
    response = batch_client.create_compute_environment(
        computeEnvironmentName=name,
        type='MANAGED',
        state='ENABLED',
        computeResources={
            'type': 'EC2',
            'minvCpus': int(config['MinvCpus']),
            'desiredvCpus': int(config['DesiredvCpus']),
            'maxvCpus': int(config['MaxvCpus']),
            'instanceTypes': config['ComputeInstanceTypes'],
            'subnets': [config['MasterSubnetId']],
            'securityGroupIds': config['SecurityGroup'],
            'ec2KeyPair': config['KeyName'],
            'instanceRole': config['InstanceRole']
        },
        serviceRole='arn:aws:iam::%s:role/AWSBatchZetaServiceRole' % config['AccountId']
    )

    poll_on_ce_status(response.get("computeEnvironmentName"))

    return response.get("computeEnvironmentArn")


def delete_compute_environment(name):
    batch_client.update_compute_environment(computeEnvironment=name, state='DISABLED')
    poll_on_ce_status(name)
    batch_client.delete_compute_environment(computeEnvironment=name)


def create_job_queue(cluster_name, compute_environment_arn):
    name = "%s-mnp" % cluster_name
    response = batch_client.create_job_queue(
        jobQueueName=name,
        state='ENABLED',
        priority=1,
        computeEnvironmentOrder=[
            {
                'order': 1,
                'computeEnvironment': compute_environment_arn
            }
        ]
    )

    poll_on_jq_status(name)

    return response.get("jobQueueArn")


def delete_job_queue(name):
    batch_client.update_job_queue(jobQueue=name, state='DISABLED')
    poll_on_jq_status(name)
    batch_client.delete_job_queue(jobQueue=name)
# Remove END -------


def retrieve_job_definition_revisions(name):
    """
    Retrieves all revisions for a given job definition
    Args:
        name: name of the job definition

    Returns:
        an array containing all job definition revisions ARNs
    """
    next_token = ''
    job_definitions = []
    while next_token is not None:
        response = batch_client.describe_job_definitions(jobDefinitionName=name, nextToken=next_token, status='ACTIVE')
        if 'jobDefinitions' in response:
            for job_definition in response['jobDefinitions']:
                job_definitions.append(job_definition['jobDefinitionArn'])
        next_token = response.get('nextToken')
        time.sleep(0.5)

    return job_definitions


def deregister_job_definition_revisions(name):
    """
    De-registers all revisions belonging to a given job definition
    Args:
        name: name of the job definition
    """
    job_definitions = retrieve_job_definition_revisions(name)
    for job_definition in job_definitions:
        try:
            logger.info('De-registering job definition: %s' % job_definition)
            batch_client.deregister_job_definition(jobDefinition=job_definition)
        except ClientError:
            logger.warning('job definition not found: %s. It was probably manually de-registered.' % job_definition)
        time.sleep(0.5)


def create_job_definition(config):
    name = "%s-mnp" % config['ClusterName']
    response = batch_client.register_job_definition(
        jobDefinitionName=name,
        type='multinode',
        nodeProperties={
            "numNodes": 1,
            "mainNode": 0,
            "nodeRangeProperties": [
                {
                    "targetNodes": "0:0",
                    "container": {
                        "image": config['DockerImage'],
                        'jobRoleArn': config['JobRole'],
                        "memory": 512,
                        "mountPoints": [],
                        "ulimits": [],
                        'privileged': True,
                        'user': 'root',
                        "vcpus": 1,
                        "environment": [
                            {
                                "name": "SHARED_DIR",
                                "value": config['SharedDir']
                            }
                        ]
                    }
                }
            ]
        }
    )

    return response.get("jobDefinitionArn"), name


def create(event, context):
    config = event['ResourceProperties']

    # ToDo: Remove after public mnp launch
    compute_environment_arn = create_compute_environment(config)
    # ToDo: Remove after public mnp launch
    job_queue_arn = create_job_queue(config['ClusterName'], compute_environment_arn)
    (job_def_arn, job_def_name) = create_job_definition(config)

    resources = {
        "ComputeEnvironment": compute_environment_arn,
        "JobQueue": job_queue_arn,
        "JobDefinitionArn": job_def_arn,
        "JobDefinitionName": job_def_name
    }

    return json.dumps(resources), resources


def update(event, context):
    return event['PhysicalResourceId'], {}


def delete(event, context):
    resources = json.loads(event['PhysicalResourceId'])

    job_definition = resources['JobDefinitionName']
    logger.info('Job definition %s deletion: STARTED' % job_definition)
    deregister_job_definition_revisions(job_definition)
    logger.info('Job definition %s deletion: COMPLETED' % job_definition)

    # ToDo: Remove after public mnp launch
    job_queue = resources['JobQueue']
    logger.info('Job queue %s deletion: STARTED' % job_queue)
    delete_job_queue(job_queue)
    logger.info('Job queue %s deletion: COMPLETED' % job_queue)

    # Sleep for 60 seconds to make sure job queue is deleted
    time.sleep(60)

    # ToDo: Remove after public mnp launch
    compute_environment = resources['ComputeEnvironment']
    logger.info('Compute environment %s deletion: STARTED' % compute_environment)
    delete_compute_environment(compute_environment)
    logger.info('Compute environment %s deletion: COMPLETED' % compute_environment)


def handler(event, context):
    """
    Main handler function, passes off it's work to crhelper's cfn_handler
    """
    # update the logger with event info
    global logger
    logger = crhelper.log_config(event, loglevel='info')
    return crhelper.cfn_handler(event, context, create, update, delete, logger, init_failed)
