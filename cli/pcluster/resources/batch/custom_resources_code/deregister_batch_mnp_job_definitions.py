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
import re
import time

import boto3
from botocore.exceptions import ClientError

import crhelper

# initialise logger
logger = crhelper.log_config({"RequestId": "CONTAINER_INIT"}, loglevel="info")
logger.info("Logging configured")
# set global to track init failures
init_failed = False

try:
    # Place initialization code here
    logger.info("Container initialization completed")
    batch_client = boto3.client("batch")
except Exception as e:
    logger.error(e, exc_info=True)
    init_failed = e


def get_job_definition_name_by_arn(job_definition_arn):
    """
    Parse Job Definition arn and get name.

    Args:
        job_definition_arn: something like arn:aws:batch:<region>:<account-id>:job-definition/<name>:<version>

    Returns: the job definition name
    """
    pattern = r".*/(.*):(.*)"
    return re.search(pattern, job_definition_arn).group(1)


def retrieve_job_definition_revisions(name):
    """
    Retrieve all revisions for a given job definition.

    Args:
        name: name of the job definition

    Returns: an array containing all job definition revisions ARNs
    """
    next_token = ""
    job_definitions = []
    while next_token is not None:
        response = batch_client.describe_job_definitions(jobDefinitionName=name, nextToken=next_token, status="ACTIVE")
        if "jobDefinitions" in response:
            for job_definition in response["jobDefinitions"]:
                job_definitions.append(job_definition["jobDefinitionArn"])
        next_token = response.get("nextToken")
        # Since it's not a time critical operation, sleeping to avoid hitting API's TPS limit.
        time.sleep(0.5)

    return job_definitions


def deregister_job_definition_revisions(name):
    """
    De-register all revisions belonging to a given job definition.

    Args:
        name: name of the job definition
    """
    job_definitions = retrieve_job_definition_revisions(name)
    for job_definition in job_definitions:
        try:
            logger.info("De-registering job definition: %s" % job_definition)
            batch_client.deregister_job_definition(jobDefinition=job_definition)
        except ClientError:
            logger.warning("job definition not found: %s. It was probably manually de-registered." % job_definition)
        # Since it's not a time critical operation, sleeping to avoid hitting API's TPS limit.
        time.sleep(0.5)


def create(event, context):
    """Noop."""
    return "MNPJobDefinitionCleanupHandler", {}


def update(event, context):
    """Noop."""
    return event["MNPJobDefinitionCleanupHandler"], {}


def delete(event, context):
    """Deregister all mnp job definitions."""
    job_definition = get_job_definition_name_by_arn(event["ResourceProperties"]["JobDefinitionMNPArn"])
    logger.info("Job definition %s deletion: STARTED" % job_definition)
    deregister_job_definition_revisions(job_definition)
    logger.info("Job definition %s deletion: COMPLETED" % job_definition)


def handler(event, context):
    """Main handler function, passes off it's work to crhelper's cfn_handler."""  # noqa: D401
    # update the logger with event info
    global logger
    logger = crhelper.log_config(event, loglevel="info")
    return crhelper.cfn_handler(event, context, create, update, delete, logger, init_failed)
