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
import sys
import tempfile
import urllib
from enum import Enum

import argparse
from s3_factory import S3DocumentManager

from common import (
    PARTITION_TO_MAIN_REGION,
    PARTITIONS,
    generate_rollback_data,
    get_aws_regions,
    retrieve_sts_credentials,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


class HashingAlgorithm(Enum):
    """Enum for hashing algorithms."""

    MD5 = "md5"
    SHA256 = "sha256"

    def __str__(self):
        return self.value


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
    parser.add_argument("--src-bucket", type=str, help="Source bucket", required=True)
    parser.add_argument("--src-bucket-region", type=str, help="Source bucket region", required=True)
    parser.add_argument("--src-files", help="Files to sync", nargs="+", required=True)
    parser.add_argument(
        "--integrity-check",
        help="If this option is specified, a file having the same name of the src files and as extension the hashing "
        "algorithm is expected to be found in the source bucket. This file is used to perform checksum validation "
        "and is also uploaded to the destination bucket",
        choices=list(HashingAlgorithm),
        type=lambda value: HashingAlgorithm(value),
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


def _checksum(filename, base64_encoded=True, algorithm=HashingAlgorithm.SHA256):
    init_function = {HashingAlgorithm.SHA256: hashlib.sha256, HashingAlgorithm.MD5: hashlib.md5}
    checksum = init_function[algorithm]()
    with open(filename, "rb") as f:
        for data in iter(lambda: f.read(1024 * 1024), b""):
            checksum.update(data)
    return base64.b64encode(checksum.digest()).decode("utf-8") if base64_encoded else checksum.hexdigest()


def _upload_files(args, files, sts_credentials, dir):
    for region in args.regions:
        for file in files:
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

            md5 = _checksum(file_path, base64_encoded=True, algorithm=HashingAlgorithm.MD5)
            logging.info("Computed md5 checksum for S3 upload: %s", md5)
            with open(file_path, "rb") as data:
                doc_manager.upload(dest_bucket, file, data, dryrun=not args.deploy, md5=md5)


def _check_file_integrity(file, checksum_file, algorithm):
    logging.info("Validating checksum for file %s", file)
    with open(checksum_file, "r") as f:
        expected_checksum = f.read().split(" ")[0]
    file_checksum = _checksum(file, False, algorithm)
    if expected_checksum != file_checksum:
        raise Exception("Computed checksum %s does not match expected one %s", file_checksum, expected_checksum)


def _download_file(url, file_path):
    logging.info("Downloading file %s and saving it to %s", url, file_path)
    urllib.request.urlretrieve(url, file_path)
    logging.info("Validating size of downloaded file")
    metadata = _get_s3_object_metadata(url)
    downloaded_file_size = os.stat(file_path).st_size
    if downloaded_file_size != int(metadata["size"]):
        raise Exception(
            f"Size of S3 object ({metadata['size']}) does not match size of downloaded file "
            f"({downloaded_file_size})"
        )


def _download_files(args, dir):
    bucket_url = (
        f"https://{args.src_bucket}.s3.{args.src_bucket_region}.amazonaws.com"
        f"{'.cn' if args.src_bucket_region.startswith('cn-') else ''}"
    )
    for file in args.src_files:
        file_path = f"{dir}/{file}"
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        url = f"{bucket_url}/{file}"
        _download_file(url, file_path)
        if args.integrity_check:
            checksum_file = f"{file_path}.{args.integrity_check}"
            _download_file(f"{url}.{args.integrity_check}", checksum_file)
            _check_file_integrity(file_path, checksum_file, args.integrity_check)


def _validate_uploaded_files(args, uploaded_files, rollback_data):
    for region in args.regions:
        bucket_name = f"{args.dest_bucket.format(region=region)}"
        bucket_url = f"https://{bucket_name}.s3.{region}.amazonaws.com{'.cn' if region.startswith('cn-') else ''}"
        for file in uploaded_files:
            url = f"{bucket_url}/{file}"
            logging.info("Validating file %s", url)
            metadata = _get_s3_object_metadata(url)
            if not metadata["version_id"]:
                logging.error("Cannot fetch object version")
            if metadata["version_id"] == rollback_data[bucket_name]["files"][file]:
                logging.error(f"Current version {metadata['version_id']} is the same as previous one")


def _check_buckets_versioning(args, sts_credentials):
    for region in args.regions:
        doc_manager = S3DocumentManager(region, sts_credentials.get(region))
        bucket_name = f"{args.dest_bucket.format(region=region)}"
        if not doc_manager.is_bucket_versioning_enabled(bucket_name):
            logging.error("Versioning is not enabled for bucket %s. Exiting...", bucket_name)
            sys.exit(1)


def main():
    args = _parse_args()
    logging.info("Parsed cli args: %s", vars(args))

    checksum_files = []
    if args.integrity_check:
        checksum_files = list(map(lambda f: f"{f}.{args.integrity_check}", args.src_files))

    logging.info("Retrieving STS credentials")
    sts_credentials = retrieve_sts_credentials(args.credentials, PARTITION_TO_MAIN_REGION[args.partition], args.regions)

    logging.info("Generating rollback data")
    rollback_data = generate_rollback_data(
        args.regions, args.dest_bucket, args.src_files + checksum_files, sts_credentials
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        logging.info("Created temporary directory %s", temp_dir)
        logging.info("Downloading the data")
        _download_files(args, temp_dir)
        logging.info("Checking S3 versioning is enabled in destination bucket before proceeding")
        _check_buckets_versioning(args, sts_credentials)
        logging.info("Copying files")
        _upload_files(args, args.src_files + checksum_files, sts_credentials, temp_dir)
        if args.deploy:
            logging.info("Validating uploaded files")
            _validate_uploaded_files(args, args.src_files + checksum_files, rollback_data)


if __name__ == "__main__":
    main()
