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
import logging
import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)
boto3_config = Config(retries={"max_attempts": 60})


def handler(event, context):
    logger.info("Printing event: %s" % json.dumps(event))
    for record in event["Records"]:
        event_message = record["Sns"]["Message"]
        logger.info("Printing event message: %s", json.dumps(event_message))

        # retrieve environment
        stack_arn = os.environ["IMAGE_STACK_ARN"]
        region = os.getenv("AWS_REGION")

        # convert the event message to json
        message_json = json.loads(event_message)

        # get image status
        try:
            image_status = message_json["state"]["status"]
        except KeyError:
            logger.error("Message doesn't contain image status notification")
            continue

        logger.info("Image status is %s", image_status)
        if image_status == "AVAILABLE":
            try:
                # delete stack
                logger.info("Deleting stack %s", stack_arn)
                cfn_client = boto3.client("cloudformation", config=boto3_config, region_name=region)
                cfn_client.delete_stack(StackName=stack_arn)
                break
            except ClientError as e:
                logging.error("Deletion of stack %s failed with exception: %s", stack_arn, e)
                raise
        else:
            logger.info("Not doing anything on stack %s", stack_arn)
