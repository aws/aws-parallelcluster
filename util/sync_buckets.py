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
import base64
import hashlib
import logging
import os
import tempfile
import urllib

import argparse

from common import (
    PARTITION_TO_MAIN_REGION,
    PARTITIONS,
    generate_rollback_data,
    get_aws_regions,
    retrieve_sts_credentials,
)
from s3_factory import S3DocumentManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


def _validate_args(args, parser):
    if not args.regions:
        parser.error("please specify --regions or --autodetect-regions")


def _parse_args():
    def _aws_credentials_type(value):
        return tuple(value.strip().split(","))

    parser = argparse.ArgumentParser(description="Sync the content of a source bucket to a set of destination buckets")
    parser.add_argument(
        "--partition", choices=PARTITIONS, help="AWS Partition where to update the files", required=True
    )
    parser.add_argument(
        "--regions",
        type=str,
        help="Regions where the files whould be deployed to",
        required=False,
        nargs="+",
        default=[],
    )
    parser.add_argument(
        "--autodetect-regions",
        action="store_true",
        help="If set ec2.describe_regions is used to retrieve regions. "
        "Additional regions (e.g. opt-in) can be specified with --regions",
        required=False,
        default=False,
    )
    parser.add_argument(
        "--dest-bucket",
        type=str,
        help="Bucket to upload to, defaults to {region}-aws-parallelcluster",
        required=False,
        default="{region}-aws-parallelcluster",
    )
    parser.add_argument(
        "--src-bucket", type=str, help="Source bucket", required=True,
    )
    parser.add_argument(
        "--src-bucket-region", type=str, help="Source bucket region", required=True,
    )
    parser.add_argument("--src-files", help="Files to sync", nargs="+", required=True)
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
        "--deploy",
        action="store_true",
        help="If deploy is false, we will perform a dryrun and no file will be pushed to buckets",
        default=False,
        required=False,
    )
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Overrides existing files in dest buckets",
        default=False,
        required=False,
    )

    args = parser.parse_args()

    if args.autodetect_regions:
        args.regions.extend(get_aws_regions(args.partition))

    _validate_args(args, parser)
    return args


def _get_s3_object_metadata(s3_url):
    req = urllib.request.Request(url=s3_url, method="HEAD")
    response = urllib.request.urlopen(req)
    assert response.status == 200
    metadata = {}
    metadata["version_id"] = response.headers.get("x-amz-version-id")
    metadata["size"] = response.headers.get("Content-Length")

    return metadata


def _md5_checksum(filename):
    m = hashlib.md5()
    with open(filename, "rb") as f:
        for data in iter(lambda: f.read(1024 * 1024), b""):
            m.update(data)
    return base64.b64encode(m.digest()).decode("utf-8")


def _upload_files(args, sts_credentials, dir):
    for region in args.regions:
        for file in args.src_files:
            logging.info("Copying file %s to region %s", file, region)
            doc_manager = S3DocumentManager(region, sts_credentials.get(region))
            file_path = f"{dir}/{file}"
            dest_bucket = args.dest_bucket.format(region=region)
            exists = doc_manager.version_exists(s3_bucket=dest_bucket, document_s3_path=file)
            if not args.update_existing and exists:
                logging.warning(
                    "Object %s already exists in %s and --update-existing flag was not specified. Skipping upload",
                    file,
                    dest_bucket,
                )
                continue

            md5 = _md5_checksum(file_path)
            logging.info("Computed md5 checksum: %s", md5)
            with open(file_path, "rb") as data:
                doc_manager.upload(dest_bucket, file, data, dryrun=not args.deploy, md5=md5)


def _download_files(args, dir):
    bucket_url = (
        f"https://{args.src_bucket}.s3.{args.src_bucket_region}.amazonaws.com"
        f"{'.cn' if args.src_bucket_region.startswith('cn-') else ''}"
    )
    for file in args.src_files:
        os.makedirs(os.path.dirname(f"{dir}/{file}"), exist_ok=True)
        url = f"{bucket_url}/{file}"
        file_path = f"{dir}/{file}"
        urllib.request.urlretrieve(url, file_path)
        logging.info("Validating size of downloaded file")
        metadata = _get_s3_object_metadata(url)
        downloaded_file_size = os.stat(file_path).st_size
        if downloaded_file_size != int(metadata["size"]):
            raise Exception(
                f"Size of S3 object ({metadata['size']}) does not match size of downloaded file "
                f"({downloaded_file_size})"
            )


def _validate_uploaded_files(args, rollback_data):
    for region in args.regions:
        bucket_name = f"{args.dest_bucket.format(region=region)}"
        bucket_url = f"https://{bucket_name}.s3.{region}.amazonaws.com{'.cn' if region.startswith('cn-') else ''}"
        for file in args.src_files:
            url = f"{bucket_url}/{file}"
            logging.info("Validating file %s", url)
            metadata = _get_s3_object_metadata(url)
            if not metadata["version_id"]:
                logging.error("Cannot fetch object version")
            if metadata["version_id"] == rollback_data[bucket_name]["files"][file]:
                logging.error(f"Current version {metadata['version_id']} is the same as previous one")


def main():
    args = _parse_args()
    logging.info("Parsed cli args: %s", vars(args))

    logging.info("Retrieving STS credentials")
    sts_credentials = retrieve_sts_credentials(args.credentials, PARTITION_TO_MAIN_REGION[args.partition], args.regions)

    logging.info("Generating rollback data")
    rollback_data = generate_rollback_data(args.regions, args.dest_bucket, args.src_files, sts_credentials)

    with tempfile.TemporaryDirectory() as temp_dir:
        logging.info("Created temporary directory %s", temp_dir)
        logging.info("Downloading the data")
        _download_files(args, temp_dir)
        logging.info("Copying files")
        _upload_files(args, sts_credentials, temp_dir)
        if args.deploy:
            logging.info("Validating uploaded files")
            _validate_uploaded_files(args, rollback_data)


if __name__ == "__main__":
    main()
