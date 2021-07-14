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


def _tag_ami(message_json):
    # tag EC2 AMI
    try:
        for ami in message_json["outputResources"]["amis"]:
            try:
                image_id = ami["image"]
                ami_region = ami["region"]
                aws_partition = message_json["arn"].split(":")[1]
                parent_image = message_json["imageRecipe"]["parentImage"]
                image_arn = f"arn:{aws_partition}:ec2:{ami_region}::image/{image_id}"
                logger.info("Tagging EC2 AMI %s", image_arn)
                tag_client = boto3.client("resourcegroupstaggingapi", config=boto3_config, region_name=ami_region)
                tag_client.tag_resources(
                    ResourceARNList=[
                        image_arn,
                    ],
                    Tags={
                        "parallelcluster:build_status": "available",
                        "parallelcluster:parent_image": parent_image,
                    },
                )
            except KeyError as e:
                logger.error("Unable to parse ami information, exception is: %s", e)
            except ClientError as e:
                logging.error("Tagging EC2 AMI %s failed with exception: %s", image_arn, e)
    except KeyError as e:
        logger.error("Message doesn't contain output amis, exception is: %s", e)


def handler(event, context):  # pylint: disable=unused-argument
    logger.info("Printing event: %s", json.dumps(event))
    for record in event["Records"]:
        event_message = record["Sns"]["Message"]
        logger.info("Printing event message: %s", json.dumps(event_message))

        # retrieve environment
        stack_arn = os.environ.get("IMAGE_STACK_ARN")
        aws_region = os.environ.get("AWS_REGION")

        # convert the event message to json
        message_json = json.loads(event_message)

        # get image status
        try:
            image_status = message_json["state"]["status"]
        except KeyError as e:
            logger.error("Message doesn't contain image status notification, exception is: %s", e)
            continue

        logger.info("Image status is %s", image_status)
        if image_status == "AVAILABLE":
            _tag_ami(message_json)
            try:
                # delete stack
                logger.info("Deleting stack %s", stack_arn)
                cfn_client = boto3.client("cloudformation", config=boto3_config, region_name=aws_region)
                cfn_client.delete_stack(StackName=stack_arn)
                break
            except ClientError as e:
                logging.error("Deletion of stack %s failed with exception: %s", stack_arn, e)
                raise
        else:
            logger.info("Not doing anything on stack %s", stack_arn)
