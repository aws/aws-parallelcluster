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

import argparse
from s3_factory import S3DocumentManager

from common import PARTITION_TO_MAIN_REGION, PARTITIONS, retrieve_sts_credentials

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


def execute_rollback(rollback_file_path, sts_credentials, deploy):
    with open(rollback_file_path) as rollback_file:
        rollback_data = json.load(rollback_file)
        logging.info("Loaded rollback data:\n%s", json.dumps(rollback_data, indent=2))

        # Rollback file format
        # {
        #     "s3_bucket": {
        #         "region": "us-east-1",
        #         "files": {
        #             "object_key": "version_id"
        #         }
        #     },
        #     ...
        # }
        for bucket_name, bucket_rollback_data in rollback_data.items():
            region = bucket_rollback_data["region"]
            for file, version in bucket_rollback_data["files"].items():
                object_manager = S3DocumentManager(region, sts_credentials.get(region))
                object_manager.revert_object(bucket_name, file, version, not deploy)


def _parse_args():
    def _aws_credentials_type(value):
        return tuple(value.strip().split(","))

    def _json_file_type(value):
        if not os.path.isfile(value):
            raise argparse.ArgumentTypeError("'{0}' is not a valid file".format(value))
        with open(value) as rollback_file:
            json.load(rollback_file)
        return value

    parser = argparse.ArgumentParser(description="Rollback S3 files to a previous version")
    parser.add_argument(
        "--rollback-file-path",
        help="Path to file containing the rollback information",
        type=_json_file_type,
        required=True,
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="If deploy is false, we will perform a dryrun and no file will be pushed to buckets",
        default=False,
        required=False,
    )
    parser.add_argument(
        "--credentials",
        help="STS credential endpoint, in the format <region>,<endpoint>,<ARN>,<externalId>."
        "Could be specified multiple times",
        required=False,
        nargs="+",
        type=_aws_credentials_type,
        default=[],
    )
    parser.add_argument(
        "--partition", choices=PARTITIONS, help="AWS Partition where to update the files", required=True
    )

    args = parser.parse_args()
    return args


def main():
    args = _parse_args()
    logging.info("Parsed cli args: %s", vars(args))

    regions = set()
    with open(args.rollback_file_path) as rollback_file:
        rollback_data = json.load(rollback_file)
        for bucket in rollback_data.keys():
            regions.add(rollback_data[bucket]["region"])

    sts_credentials = retrieve_sts_credentials(args.credentials, PARTITION_TO_MAIN_REGION[args.partition], regions)
    execute_rollback(args.rollback_file_path, sts_credentials, args.deploy)


if __name__ == "__main__":
    main()
