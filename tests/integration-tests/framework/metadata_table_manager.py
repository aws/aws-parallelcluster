#  Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.

import logging
import uuid
from dataclasses import dataclass
from typing import List

import boto3
import botocore.exceptions


@dataclass
class PhaseMetadata:
    """Metadata for a phase of a test"""

    name: str
    status: str = ""
    start_time: float = 0.0
    end_time: float = 0.0


@dataclass
class TestMetadata:
    """Metadata for a test"""

    name: str
    id: str = uuid.uuid4().hex
    region: str = ""
    os: str = ""
    feature: str = ""
    instance_type: str = ""
    setup_metadata: PhaseMetadata = PhaseMetadata(name="setup")
    call_metadata: PhaseMetadata = PhaseMetadata(name="call")
    teardown_metadata: PhaseMetadata = PhaseMetadata(name="teardown")
    cli_commit: str = ""
    cookbook_commit: str = ""
    node_commit: str = ""
    cfn_stack_name: str = ""
    cw_log_group_name: str = ""
    global_build_number: int = 0


@dataclass
class MetadataTableManager:
    """Publishes test metadata to the corresponding DynamoDB table"""

    table: str
    client: boto3.client

    def __init__(self, region, table):
        self.client = boto3.client("dynamodb", region_name=region)
        self.table = table

    def create_metadata_table(self) -> bool:
        """Creates the metadata table in DynamoDB"""
        try:
            # Check if the table exists already
            describe_result = self.client.describe_table(TableName=self.table)
            logging.info(f"Table exists: {describe_result}")
            return True
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logging.info("The metadata table does not exist. Creating it now.")
            else:
                raise e

        self.client.create_table(
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            TableName=self.table,
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        logging.info(f"Successfully created metadata table: {self.table}")
        return True

    def publish_metadata(self, metadata: List[TestMetadata]):
        """Publishes test metadata to the table"""
        for datum in metadata:
            try:
                self.client.put_item(
                    TableName=self.table,
                    Item={
                        "id": {"S": datum.id},
                        "name": {"S": datum.name},
                        "region": {"S": datum.region},
                        "os": {"S": datum.os},
                        "feature": {"S": datum.feature},
                        "instance_type": {"S": datum.instance_type},
                        "setup_status": {"S": datum.setup_metadata.status},
                        "setup_start_time": {"N": str(datum.setup_metadata.start_time)},
                        "setup_end_time": {"N": str(datum.setup_metadata.end_time)},
                        "call_status": {"S": datum.call_metadata.status},
                        "call_start_time": {"N": str(datum.call_metadata.start_time)},
                        "call_end_time": {"N": str(datum.call_metadata.end_time)},
                        "teardown_status": {"S": datum.teardown_metadata.status},
                        "teardown_start_time": {"N": str(datum.teardown_metadata.start_time)},
                        "teardown_end_time": {"N": str(datum.teardown_metadata.end_time)},
                        "cli_commit": {"S": datum.cli_commit},
                        "cookbook_commit": {"S": datum.cookbook_commit},
                        "node_commit": {"S": datum.node_commit},
                        "cfn_stack_name": {"S": datum.cfn_stack_name},
                        "cw_log_group_name": {"S": datum.cw_log_group_name},
                        "global_build_number": {"N": str(datum.global_build_number)},
                    },
                )
            except Exception as e:
                logging.error(f"Failed to publish {datum} to metadata table with {e}")
            logging.info(f"Successfully published {datum} to metadata table: {self.table}")

    def get_metadata(self, ids: List[str]) -> List[TestMetadata]:
        """Gets the metadata item from the table"""
        items = []
        for test_id in ids:
            response = self.client.get_item(Key={"id": {"S": test_id}}, TableName=self.table)
            logging.info(f"Successfully got metadata item from metadata table: {self.table}")
            if "Item" in response:
                logging.info(response["Item"])
                items.append(
                    TestMetadata(
                        id=response["Item"]["id"]["S"],
                        name=response["Item"]["name"]["S"],
                        region=response["Item"]["region"]["S"],
                        os=response["Item"]["os"]["S"],
                        feature=response["Item"]["feature"]["S"],
                        instance_type=response["Item"]["instance_type"]["S"],
                        setup_metadata=PhaseMetadata(
                            name="setup",
                            status=response["Item"]["setup_status"]["S"],
                            start_time=float(response["Item"]["setup_start_time"]["N"]),
                            end_time=float(response["Item"]["setup_end_time"]["N"]),
                        ),
                        call_metadata=PhaseMetadata(
                            name="call",
                            status=response["Item"]["call_status"]["S"],
                            start_time=float(response["Item"]["call_start_time"]["N"]),
                            end_time=float(response["Item"]["call_end_time"]["N"]),
                        ),
                        teardown_metadata=PhaseMetadata(
                            name="teardown",
                            status=response["Item"]["teardown_status"]["S"],
                            start_time=float(response["Item"]["teardown_start_time"]["N"]),
                            end_time=float(response["Item"]["teardown_end_time"]["N"]),
                        ),
                        cli_commit=response["Item"]["cli_commit"]["S"],
                        cookbook_commit=response["Item"]["cookbook_commit"]["S"],
                        node_commit=response["Item"]["node_commit"]["S"],
                        cfn_stack_name=response["Item"]["cfn_stack_name"]["S"],
                        cw_log_group_name=response["Item"]["cw_log_group_name"]["S"],
                        global_build_number=int(response["Item"]["global_build_number"]["N"]),
                    )
                )
            else:
                logging.info("No metadata item found in the table")
        logging.info(f"Successfully got items: {items} from metadata table: {self.table}")
        return items
