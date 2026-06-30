#!/usr/bin/python
#
# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not
# use this file except in compliance with the License. A copy of the License
# is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, express or implied. See the License for the specific language
# governing permissions and limitations under the License.
#
#
# Shared S3 upload helpers used by the release artifact uploaders
# (upload-node.py, upload-cookbook.py). These scripts push an artifact (plus its
# .md5 and .tgz.date sidecars) to the per-region <region>-aws-parallelcluster
# buckets, optionally assuming an STS role for opt-in regions.
import hashlib
import os
import sys
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

PARTITION_MAIN_REGION = {
    "commercial": "us-east-1",
    "govcloud": "us-gov-west-1",
    "china": "cn-north-1",
}


def add_common_arguments(parser):
    """Add the CLI arguments shared by all artifact uploaders. Callers add their
    own artifact-path argument (e.g. --node-archive-path)."""
    parser.add_argument(
        "--regions",
        type=str,
        help='Valid Regions, can include "all", or comma separated list of regions',
        required=True,
    )
    parser.add_argument(
        "--unsupportedregions", type=str, help="Unsupported regions, comma separated", default="", required=False
    )
    parser.add_argument(
        "--override",
        action="store_true",
        help="If override is false, the file will not be pushed if it already exists in the bucket",
        default=False,
        required=False,
    )
    parser.add_argument(
        "--bucket", type=str, help="Buckets to upload to, defaults to [region]-aws-parallelcluster", required=False
    )
    parser.add_argument(
        "--dryrun", action="store_true", help="Doesn't push anything to S3, just outputs", default=False, required=False
    )
    parser.add_argument("--partition", type=str, help="commercial | china | govcloud", required=True)
    parser.add_argument(
        "--credential",
        type=str,
        action="append",
        help="STS credential endpoint, in the format <region>,<endpoint>,<ARN>,<externalId>. "
        "Could be specified multiple times",
        required=False,
    )
    return parser


class S3Uploader:
    """Pushes a release artifact and its sidecars to the per-region S3 buckets."""

    def __init__(self, artifact_dir, sts_session_name):
        # S3 key prefix the artifact lives under, e.g. parallelcluster/<version>/node
        self.artifact_dir = artifact_dir
        self.backup_dir = "{0}/backup".format(artifact_dir)
        self.sts_session_name = sts_session_name
        self.bck_date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.bck_error_array = set()
        self.cp_error_array = set()
        self.ls_error_array = set()
        self.credentials = []
        self.main_region = None

    def resolve_args(self, args):
        """Resolve partition -> main region, parse opt-in credentials, and expand
        the region list (handling "all" and purging unsupported regions)."""
        self.main_region = PARTITION_MAIN_REGION.get(args.partition)
        if self.main_region is None:
            print("Unsupported partition {0}".format(args.partition))
            sys.exit(1)

        if args.credential:
            self.credentials = [
                tuple(credential_tuple.strip().split(","))
                for credential_tuple in args.credential
                if credential_tuple.strip()
            ]

        if args.regions == "all":
            args.regions = self.get_all_aws_regions(self.main_region)
        else:
            args.regions = [x.strip() for x in args.regions.split(",")]

        args.unsupportedregions = [x.strip() for x in args.unsupportedregions.split(",")]

        # Purging regions
        args.regions = set(args.regions) - set(args.unsupportedregions)

        # Adds all opt-in regions
        for credential in self.credentials:
            args.regions.add(credential[0])

        return args

    @staticmethod
    def get_all_aws_regions(region):
        ec2 = boto3.client("ec2", region_name=region)
        return set(sorted(r.get("RegionName") for r in ec2.describe_regions().get("Regions")))

    @staticmethod
    def get_bucket_name(args, region):
        return region + "-aws-parallelcluster" if not args.bucket else args.bucket

    @staticmethod
    def md5sum(archive_file, md5sum_file):
        blocksize = 65536
        # MD5 used for a checksum/integrity manifest, not for security.
        hasher = hashlib.md5(usedforsecurity=False)
        with open(archive_file, "rb") as arch:
            buf = arch.read(blocksize)
            while len(buf) > 0:
                hasher.update(buf)
                buf = arch.read(blocksize)

        with open(md5sum_file, "w+", encoding="utf-8") as md5:
            md5.write("{0}  {1}".format(hasher.hexdigest(), os.path.basename(archive_file)))

    def create_s3_client(self, region):
        reg_credentials = [c for c in self.credentials if c[0] == region]

        if reg_credentials:
            credential = reg_credentials[0]
            credential_region = credential[0]
            credential_endpoint = credential[1]
            credential_arn = credential[2]
            credential_external_id = credential[3]

            try:
                sts = boto3.client("sts", region_name=self.main_region, endpoint_url=credential_endpoint)

                assumed_role_object = sts.assume_role(
                    RoleArn=credential_arn,
                    ExternalId=credential_external_id,
                    RoleSessionName=credential_region + self.sts_session_name,
                )
                aws_credentials = assumed_role_object["Credentials"]
                s3 = boto3.client(
                    "s3",
                    region_name=credential_region,
                    aws_access_key_id=aws_credentials.get("AccessKeyId"),
                    aws_secret_access_key=aws_credentials.get("SecretAccessKey"),
                    aws_session_token=aws_credentials.get("SessionToken"),
                )

            except ClientError as e:
                print("Warning: non authorized in region '{0}', skipping".format(credential_region))
                raise e
        else:
            s3 = boto3.client("s3", region_name=region)
        return s3

    def aws_s3_ls(self, s3, region, bucket_name, key):
        out = s3.list_objects_v2(Bucket=bucket_name, Prefix=key)
        if len(out.get("Contents", [])) > 0:
            self.ls_error_array.add(region)

    def aws_s3_bck(self, s3, args, region, bucket_name, full_name):
        if args.dryrun:
            print(
                "Not backing up {0} to bucket {1} override is {2}, dryrun is {3}".format(
                    full_name, bucket_name, args.override, args.dryrun
                )
            )
        else:
            try:
                copy_source = {"Bucket": bucket_name, "Key": self.artifact_dir + "/" + full_name}
                s3.copy(copy_source, bucket_name, self.backup_dir + "/" + full_name + self.bck_date)
            except ClientError as e:
                print("Couldn't backup {0}".format(full_name))
                if e.response["Error"]["Code"] == "NoSuchBucket":
                    print("Bucket is not present.")
                self.bck_error_array.add(region)

    def aws_s3_cp(self, s3, args, region, bucket_name, folder, src_file):
        key = folder + "/" + os.path.basename(src_file)
        print("Bucket dest key: {0}".format(key))
        if args.dryrun:
            print(
                "Not uploading {0} to bucket {1}, override is {2}, dryrun is {3}".format(
                    src_file, bucket_name, args.override, args.dryrun
                )
            )
        else:
            try:
                s3.upload_file(src_file, bucket_name, key, ExtraArgs={"ACL": "public-read"})

                print("Successfully uploaded {0} to s3://{1}/{2}".format(src_file, bucket_name, key))
            except ClientError as e:
                print("Couldn't upload {0} to bucket s3://{1}/{2}".format(src_file, bucket_name, key))
                self.cp_error_array.add(region)
                if e.response["Error"]["Code"] == "NoSuchBucket":
                    print("Bucket is not present.")

                raise e
