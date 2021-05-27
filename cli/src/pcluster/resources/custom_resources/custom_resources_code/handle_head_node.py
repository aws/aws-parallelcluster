# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with
#  the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import logging

import boto3
from crhelper import CfnResource

helper = CfnResource(json_logging=False, log_level="INFO", boto_level="ERROR", sleep_on_delete=0)

# Logging
logger = logging.getLogger()

# Clients
EC2 = boto3.client("ec2")
LAMBDA = boto3.client("lambda")


@helper.delete
@helper.update
def no_op(_, __):
    pass


@helper.create
def create(event, _):
    logger.info(f"Handling CREATE event: {event}")

    cluster_name = event["ResourceProperties"]["ClusterName"]
    lambda_name = event["ResourceProperties"]["AwsCredentialsLambda"]
    filters = [
        {"Name": "tag:parallelcluster:cluster-name", "Values": [cluster_name]},
        {"Name": "tag:parallelcluster:node-type", "Values": ["HeadNode"]},
    ]

    logger.info(f"Waiting head node for cluster {cluster_name} to be running")
    EC2.get_waiter("instance_running").wait(Filters=filters, WaiterConfig={"Delay": 10, "MaxAttempts": 30})

    logger.info(f"Waiting lambda function to be active: {lambda_name}")
    LAMBDA.get_waiter("function_active").wait(FunctionName=lambda_name, WaiterConfig={"Delay": 5, "MaxAttempts": 60})

    logger.info(f"Invoking lambda function: {lambda_name}")
    LAMBDA.invoke(FunctionName=lambda_name, InvocationType="Event")


def handler(event, context):
    helper(event, context)
