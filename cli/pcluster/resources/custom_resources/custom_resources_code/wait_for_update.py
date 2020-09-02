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
import logging
import time

import boto3
from botocore.config import Config
from crhelper import CfnResource

helper = CfnResource(json_logging=False, log_level="INFO", boto_level="ERROR", sleep_on_delete=0)
logger = logging.getLogger(__name__)
boto3_config = Config(retries={"max_attempts": 60})


@helper.create
@helper.delete
def no_op(_, __):
    pass


@helper.update
def update(event, _):
    updated_config_version = event["ResourceProperties"]["ConfigVersion"]
    logging.info("Updated config version: %s", updated_config_version)
    table_name = event["ResourceProperties"]["DynamoDBTable"]
    dynamodb_table = boto3.resource("dynamodb").Table(table_name)
    current_config_version = None
    while updated_config_version != current_config_version:
        try:
            logging.info("Waiting for config version to be updated")
            cluster_config_item = dynamodb_table.get_item(ConsistentRead=True, Key={"Id": "CLUSTER_CONFIG"})
            if cluster_config_item and "Item" in cluster_config_item:
                current_config_version = cluster_config_item["Item"].get("Version")
                logger.info("Current config version: %s", current_config_version)
            time.sleep(30)
        except Exception as e:
            logging.exception(e)


def handler(event, context):
    helper(event, context)
