#!/usr/bin/python
# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import json
import logging
import os

import boto3
from s3_factory import S3DocumentManager

PARTITION_TO_MAIN_REGION = {"commercial": "us-east-1", "govcloud": "us-gov-west-1", "china": "cn-north-1"}
PARTITIONS = ["commercial", "china", "govcloud"]
FILE_TO_S3_PATH = {"instances": "instances/instances.json", "feature_whitelist": "features/feature_whitelist.json"}


def get_aws_regions(partition):
    ec2 = boto3.client("ec2", region_name=PARTITION_TO_MAIN_REGION[partition])
    return set(r.get("RegionName") for r in ec2.describe_regions().get("Regions"))


def retrieve_sts_credentials(credentials, client_region, regions):
    """
    Given credentials from cli, returns a json credentials object.

    {
        'us-east-1': {
            'aws_access_key_id': 'sjkdnf',
            'aws_secret_access_key': 'ksjdfkjsd',
            'aws_session_token': 'skajdfksdjn'
        }
        ...
    }

    :param credentials: STS credential endpoint, in the format <region>,<endpoint>,<ARN>,<externalId>.
                        Could be specified multiple times
    :param client_region: region of the client that is assuming the role
    :return: sts credentials json
    """
    sts_credentials = {}
    for credential in credentials:
        region, endpoint, arn, external_id = credential
        sts = boto3.client("sts", region_name=client_region, endpoint_url=endpoint)
        assumed_role_object = sts.assume_role(
            RoleArn=arn, ExternalId=external_id, RoleSessionName=region + "-upload_instance_slot_map_sts_session"
        )
        sts_credentials[region] = {
            "aws_access_key_id": assumed_role_object["Credentials"].get("AccessKeyId"),
            "aws_secret_access_key": assumed_role_object["Credentials"].get("SecretAccessKey"),
            "aws_session_token": assumed_role_object["Credentials"].get("SessionToken"),
        }

    if sts_credentials.get("default"):
        for region in regions:
            if region not in sts_credentials:
                sts_credentials[region] = sts_credentials["default"]

    return sts_credentials


def generate_rollback_data(regions, dest_bucket, files, sts_credentials):
    rollback_data = {}
    for region in regions:
        bucket_name = dest_bucket.format(region=region)
        rollback_data[bucket_name] = {"region": region, "files": {}}
        doc_manager = S3DocumentManager(region, sts_credentials.get(region))
        for file_type in files:
            s3_path = FILE_TO_S3_PATH.get(file_type, file_type)
            version = doc_manager.get_current_version(
                dest_bucket.format(region=region),
                s3_path,
                raise_on_object_not_found=False,
            )
            rollback_data[bucket_name]["files"][s3_path] = version

    logging.info("Rollback data:\n%s", json.dumps(rollback_data, indent=2))
    rollback_file_name = "rollback-data.json"
    with open(rollback_file_name, "w") as outfile:
        json.dump(rollback_data, outfile, indent=2)
    logging.info("Rollback data file created to: %s", f"{os.getcwd()}/{rollback_file_name}")

    return rollback_data
