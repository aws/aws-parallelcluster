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
from os import getenv
from time import sleep

import boto3
from botocore.exceptions import WaiterError

# Environment Variables
CLUSTER_NAME = getenv("CLUSTER_NAME")
ROLE_ARN = getenv("ROLE_ARN")
SSM_CW_LOG_GROUP_NAME = getenv("SSM_CW_LOG_GROUP_NAME")
SSM_CW_LOG_GROUP_ENABLED = bool(getenv("SSM_CW_LOG_GROUP_ENABLED"))

# Logging
log = logging.getLogger()
log.setLevel(logging.INFO)

# Clients
EC2 = boto3.client("ec2")
STS = boto3.client("sts")
SSM = boto3.client("ssm")


def handler(event, context):
    log.debug(f"Received event: {event}")

    head_node_instance_id, head_node_instance_state = get_head_node_instance_id(CLUSTER_NAME)

    if head_node_instance_state != "running":
        log.warning(f"Head node not running (state: {head_node_instance_state}). Skipping workflow.")
        return 304, "UNMODIFIED"

    assumed_role_arn, credentials = get_credentials(ROLE_ARN)

    write_credentials_to_node(head_node_instance_id, assumed_role_arn, credentials)

    return 200, "SUCCESS"


def get_head_node_instance_id(cluster_name):
    log.info(f"Retrieving head node for cluster: {cluster_name}")

    filters = [
        {"Name": "tag:parallelcluster:cluster-name", "Values": [cluster_name]},
        {"Name": "tag:parallelcluster:node-type", "Values": ["HeadNode"]},
    ]

    response = EC2.describe_instances(Filters=filters)

    log.debug(f"EC2.describe_instances response: {response}")

    reservations = response["Reservations"]

    if len(reservations) != 1 or len(reservations[0]["Instances"]) != 1:
        raise Exception(
            f"Found {len(reservations)} instances matching head node for cluster {cluster_name}, but expected 1"
        )

    head_node_instance = reservations[0]["Instances"][0]
    head_node_instance_id = head_node_instance["InstanceId"]
    head_node_instance_state = head_node_instance["State"]["Name"]

    log.info(f"Head node instance found: {head_node_instance_id} (state: {head_node_instance_state})")

    return head_node_instance_id, head_node_instance_state


def get_credentials(role_arn):
    log.info(f"Retrieving credentials for role: {role_arn}")

    response = STS.assume_role(RoleArn=role_arn, RoleSessionName="cluster-admin")

    log.debug(f"STS.assume_role response: {response}")

    assumed_role_arn = response["AssumedRoleUser"]["Arn"]

    credentials = {
        "aws_acces_key_id": response["Credentials"]["AccessKeyId"],
        "aws_secret_access_key": response["Credentials"]["SecretAccessKey"],
        "aws_session_token": response["Credentials"]["SessionToken"],
    }

    log.info(f"Credentials retrieved for assumable role: {assumed_role_arn}")

    return assumed_role_arn, credentials


def write_credentials_to_node(instance_id, assumed_role, credentials):
    log.info(f"Writing credentials to instance {instance_id} for role: {assumed_role}")

    response = SSM.send_command(
        DocumentName="AWS-RunShellScript",
        InstanceIds=[instance_id],
        Parameters={"commands": get_ssm_commands(assumed_role, credentials), "executionTimeout": ["10"]},
        Comment=f"Write AWS Credentials to Cluster Head Node: {CLUSTER_NAME}/{instance_id}",
        TimeoutSeconds=30,
        CloudWatchOutputConfig={
            "CloudWatchLogGroupName": SSM_CW_LOG_GROUP_NAME,
            "CloudWatchOutputEnabled": SSM_CW_LOG_GROUP_ENABLED,
        },
    )

    log.debug(f"SSM.send_command response: {response}")

    command_id = response["Command"]["CommandId"]

    log.info(f"Waiting for SSM command to succeed: {command_id}")

    # Sleep time required to avoid InvocationDoesNotExist errors on the SSM waiter due to latency issues
    sleep(5)

    try:
        SSM.get_waiter("command_executed").wait(
            CommandId=command_id, InstanceId=instance_id, WaiterConfig={"Delay": 3, "MaxAttempts": 20}
        )
    except WaiterError:
        response = SSM.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
        status = response["Status"]
        status_details = response["StatusDetails"]
        if status == "TimedOut":
            error_info = "SSM Agent may not be running on instance."
        else:
            error_info = f"Command stderr: {response['StandardErrorContent']}"
        error_message = (
            f"SSM command {command_id} failed on instance {instance_id} "
            f"with status {status} ({status_details}). "
            f"{error_info}"
        )
        log.error(error_message)
        raise Exception(error_message)

    log.info("Credentials written to node")


def get_ssm_commands(assumed_role, credentials):
    script = f"""
AWS_IAM_ASSUMED_ROLE_ARN={assumed_role}
AWS_ACCESS_KEY_ID={credentials["aws_acces_key_id"]}
AWS_SECRET_ACCESS_KEY={credentials["aws_secret_access_key"]}
AWS_SESSION_TOKEN={credentials["aws_session_token"]}

# cfnconfig: contains node variables
source "/etc/parallelcluster/cfnconfig"
SCRIPT="$scripts_dir/ssm/write_aws_credentials.sh"

bash $SCRIPT $AWS_IAM_ASSUMED_ROLE_ARN $AWS_ACCESS_KEY_ID $AWS_SECRET_ACCESS_KEY $AWS_SESSION_TOKEN
"""

    return script.split("\n")
