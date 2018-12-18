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
import boto3

import crhelper

# initialise logger
logger = crhelper.log_config({"RequestId": "CONTAINER_INIT"})
logger.info("Logging configured")
# set global to track init failures
init_failed = False

try:
    # Place initialization code here
    logger.info("Container initialization completed")
except Exception as e:
    logger.error(e, exc_info=True)
    init_failed = e


def delete_s3_bucket(bucket_name):
    """
    Empty and delete the bucket passed as argument.

    It exits gracefully if bucket doesn't exist.
    Args:
        bucket_name: bucket to delete
    """
    try:
        bucket = boto3.resource("s3").Bucket(bucket_name)
        bucket.objects.all().delete()
        bucket.delete()
    except boto3.client("s3").exceptions.NoSuchBucket as ex:
        logger.warning("S3 bucket %s not found. Bucket was probably manually deleted." % bucket_name)
        logger.warning(ex, exc_info=True)


def create(event, context):
    """Noop."""
    return "PhysicalResourceId", {}


def update(event, context):
    """Noop."""
    return event["PhysicalResourceId"], {}


def delete(event, context):
    """Delete the ResourcesS3Bucket passed in ResourceProperties object."""
    resources_s3_bucket = event["ResourceProperties"]["ResourcesS3Bucket"]
    logger.info("S3 bucket %s deletion: STARTED" % resources_s3_bucket)
    delete_s3_bucket(resources_s3_bucket)
    logger.info("S3 bucket %s deletion: COMPLETED" % resources_s3_bucket)


def handler(event, context):
    """Main handler function, passes off it's work to crhelper's cfn_handler."""  # noqa: D401
    # update the logger with event info
    global logger
    logger = crhelper.log_config(event, loglevel="info")
    return crhelper.cfn_handler(event, context, create, update, delete, logger, init_failed)
