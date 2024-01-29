# Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import string

import boto3
from botocore.config import Config
from constants import CLUSTER_CONFIG_DDB_ID
from crhelper import CfnResource
from utils.ec2_utils import list_cluster_instance_ids_iterator
from utils.retry_utils import retry

helper = CfnResource(json_logging=False, log_level="INFO", boto_level="ERROR", sleep_on_delete=0)
logger = logging.getLogger(__name__)
BOTO3_CONFIG = Config(retries={"max_attempts": 60})
BATCH_SIZE = 500


@retry(max_retries=5, wait_time_seconds=3)
def _get_cluster_config_records(table_name: str, instance_ids: [string]):
    ddb = boto3.client("dynamodb", config=BOTO3_CONFIG)

    if not instance_ids:
        logger.warning("No instances to retrieve cluster config records for")
        return []

    item_ids = [CLUSTER_CONFIG_DDB_ID.format(instance_id=instance_id) for instance_id in instance_ids]
    requested_keys = [{"Id": {"S": item_id}} for item_id in item_ids]

    try:
        response = ddb.batch_get_item(RequestItems={table_name: {"Keys": requested_keys}})
        items = response.get("Responses", {}).get(table_name, [])
    except Exception as e:
        raise RuntimeError(f"Cannot read config versions due to DDB error: {e}")

    return items


def _check_cluster_config_items(instance_ids: [str], items: [{}], expected_config_version: str):
    missing = []
    incomplete = []
    wrong = []

    if not instance_ids:
        logger.warning("No instances to check cluster config version for")
        return missing, incomplete, wrong

    # Transform DDB items to make it easier to search.
    # Example: the original items:
    # [
    #   { "Id": { "S": "CLUSTER_CONFIG.i-123456789" },
    #     "Data": {
    #       "M": {
    #         "cluster_config_version": { "HoqyEZYBkMig3gSxaMARUv0NGcG0rrso" },
    #         "lastUpdateTime": { "2024-01-16 18:59:18 UTC" }
    #       }
    #     }
    #   }
    # ]
    #
    # is transformed into items_by_id:
    #
    # {
    #   "CLUSTER_CONFIG.i-123456789": {
    #     "cluster_config_version": { "HoqyEZYBkMig3gSxaMARUv0NGcG0rrso" },
    #     "lastUpdateTime": { "2024-01-16 18:59:18 UTC" }
    #   }
    # }
    items_by_id = {item["Id"]["S"]: item["Data"]["M"] for item in items}

    for instance_id in instance_ids:
        key = CLUSTER_CONFIG_DDB_ID.format(instance_id=instance_id)
        data = items_by_id.get(key)
        if data is None:
            logger.warning(f"Missing cluster config record for instance {instance_id}")
            missing.append(instance_id)
            continue
        cluster_config_version = data.get("cluster_config_version", {}).get("S")
        if cluster_config_version is None:
            logger.warning(f"Missing cluster config version in data for instance {instance_id}")
            incomplete.append(instance_id)
            continue
        if cluster_config_version != expected_config_version:
            logger.warning(
                f"Wrong cluster config version for instance {instance_id}; "
                f"expected {expected_config_version}, but got {cluster_config_version}"
            )
            wrong.append(instance_id)

    return missing, incomplete, wrong


@retry(max_retries=5, wait_time_seconds=180)
def check_compute_nodes_config_version(cluster_name: str, table_name: str, expected_config_version: str):
    """
    Verify that every compute node in the cluster has deployed the expected config version.

    The verification is made by checking the config version reported by compute nodes on the cluster DDB table.
    A RuntimeError exception is raised if the check fails.
    The function is retried and the wait time is expected to be in the interval (cfn_hup_time, 2*cfn_hup_time),
    where cfn_hup_time is the wait time for the cfn-hup daemon (as of today it is 120 seconds).

    :param cluster_name: name of the cluster.
    :param table_name: DDB table to read the deployed config version from.
    :param expected_config_version: expected config version
    :return: None
    """
    ec2 = boto3.client("ec2", config=BOTO3_CONFIG)

    logger.info(
        f"Checking that cluster configuration deployed on compute nodes for cluster {cluster_name} "
        f"is {expected_config_version}"
    )

    for instance_ids in list_cluster_instance_ids_iterator(
        cluster_name=cluster_name, node_type=["Compute"], batch_size=BATCH_SIZE, ec2_client=ec2
    ):
        n_instance_ids = len(instance_ids)

        if not n_instance_ids:
            logger.warning("Found empty batch of compute nodes: nothing to check")
            continue

        logger.info(f"Found batch of {n_instance_ids} compute node(s): {instance_ids}")

        items = _get_cluster_config_records(table_name, instance_ids)
        logger.info(f"Retrieved {len(items)} item(s): {items}")

        missing, incomplete, wrong = _check_cluster_config_items(instance_ids, items, expected_config_version)

        if missing or incomplete or wrong:
            raise RuntimeError(
                f"Check failed due to the following erroneous records:\n"
                f"  * missing records ({len(missing)}): {missing}\n"
                f"  * incomplete records ({len(incomplete)}): {incomplete}\n"
                f"  * wrong records ({len(wrong)}): {wrong}"
            )
        else:
            logger.info(f"Verified cluster configuration for instance(s) {instance_ids}")


@helper.create
@helper.update
def create_update(event, _):
    request, properties = event["RequestType"], event["ResourceProperties"]
    logger.info(f"Received request {request} with properties: {properties}")

    check_compute_nodes_config_version(
        cluster_name=properties["ClusterName"],
        table_name=properties["TableName"],
        expected_config_version=properties["ConfigVersion"],
    )

    logger.info("All checks succeeded")


@helper.delete
def delete(event, _):
    request, properties = event["RequestType"], event["ResourceProperties"]
    logger.info(f"Received request {request} with properties: {properties}")
    logger.info("Nothing to do")


def handler(event, context):
    helper(event, context)


if __name__ == "__main__":
    import sys

    request_type, cluster_name, table_name, config_version = sys.argv[1:5]

    event = {
        "RequestType": request_type,
        "ResourceProperties": {
            "ClusterName": cluster_name,
            "TableName": table_name,
            "ConfigVersion": config_version,
        },
    }

    context = {}

    create_update(event, context)
