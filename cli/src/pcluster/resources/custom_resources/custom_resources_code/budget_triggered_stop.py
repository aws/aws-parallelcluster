import datetime
import os
import time

import boto3
from boto3.dynamodb.conditions import Attr

DB_KEY = "COMPUTE_FLEET"
DB_DATA = "Data"

COMPUTE_FLEET_STATUS_ATTRIBUTE = "status"
COMPUTE_FLEET_LAST_UPDATED_TIME_ATTRIBUTE = "lastStatusUpdatedTime"


def update_item(table, status, current_status):
    table.update_item(
        Key={"Id": DB_KEY},
        UpdateExpression="set #dt.#st=:s, #dt.#lut=:t",
        ExpressionAttributeNames={
            "#dt": DB_DATA,
            "#st": COMPUTE_FLEET_STATUS_ATTRIBUTE,
            "#lut": COMPUTE_FLEET_LAST_UPDATED_TIME_ATTRIBUTE,
        },
        ExpressionAttributeValues={
            ":s": str(status),
            ":t": str(datetime.datetime.now(tz=datetime.timezone.utc)),
        },
        ConditionExpression=Attr(f"{DB_DATA}.{COMPUTE_FLEET_STATUS_ATTRIBUTE}").eq(str(current_status)),
    )


def update_status_with_last_updated_time(table_name, region, status):
    try:
        table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        current_status = get_dynamo_db_data(table).get(COMPUTE_FLEET_STATUS_ATTRIBUTE)
        print("Stopping Compute Fleet - Triggered by Budget Threshold.")
        if current_status == status:
            return
        elif current_status in ["RUNNING", "PROTECTED"]:
            update_item(table, status, current_status)
        else:
            raise Exception(f"Could not update compute fleet status from '{current_status}' to {status}.")
    except Exception as e:
        raise Exception(f"Failed when updating fleet status with error: {e}")


def get_dynamo_db_data(table):
    try:
        compute_fleet_item = table.get_item(ConsistentRead=True, Key={"Id": DB_KEY})
        if not compute_fleet_item or "Item" not in compute_fleet_item:
            raise Exception("COMPUTE_FLEET data not found in db table")
        db_data = compute_fleet_item["Item"].get(DB_DATA)
        return db_data
    except Exception as e:
        raise Exception(f"Failed when retrieving data from DynamoDB with error {e}.")


def handler(*args, attempt=0):
    try:
        if os.environ.get("IS_BATCH") == "TRUE":
            boto3.client("batch").update_compute_environment(
                computeEnvironment=os.environ.get("CE_NAME"),
                state="DISABLED",
            )
        else:
            update_status_with_last_updated_time(
                os.environ.get("TABLE_NAME"),
                os.environ.get("AWS_REGION"),
                "STOP_REQUESTED",
            )

    except Exception as e:
        print(f"ERROR: Failed to update compute fleet status, exception: {e}")
        if attempt < 3:
            time.sleep(60)
            handler(*args, attempt=attempt + 1)
        else:
            return
