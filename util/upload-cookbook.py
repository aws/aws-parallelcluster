#!/usr/bin/python
#
# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
# Upload cookbook
#
# usage: ./upload-cookbook.py --regions "<region>[,<region>, ...]" --full_name "<cookbook name without extension>" \
# --partition <partition> \
# [--unsupportedregions "<region>[, <region>, ...]"] [--dryrun] [--override] \
# [--credential <region>,<endpoint>,<arn>,<role>]*
import hashlib
import os
from datetime import datetime

import argparse
import boto3
from botocore.exceptions import ClientError

_COOKBOOKS_DIR = "cookbooks"
_BACKUP_DIR = "{0}/backup".format(_COOKBOOKS_DIR)
_bck_date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
_bck_error_array = set()
_cp_error_array = set()
_ls_error_array = set()
_credentials = []
_main_region = None


def _get_all_aws_regions(region):
    ec2 = boto3.client("ec2", region_name=region)
    return set(sorted(r.get("RegionName") for r in ec2.describe_regions().get("Regions")))


def _aws_s3_ls(s3, region, bucket_name, key):
    out = s3.list_objects_v2(Bucket=bucket_name, Prefix=key)
    if len(out.get("Contents", [])) > 0:
        _ls_error_array.add(region)


def _aws_s3_bck(s3, args, region, bucket_name, full_name):
    if args.dryrun:
        print(
            "Not backing up {0} to bucket {1} override is {2}, dryrun is {3}".format(
                full_name, bucket_name, args.override, args.dryrun
            )
        )
    else:
        try:
            copy_source = {"Bucket": bucket_name, "Key": _COOKBOOKS_DIR + "/" + full_name}
            s3.copy(copy_source, bucket_name, _BACKUP_DIR + "/" + full_name + _bck_date)
        except ClientError as e:
            print("Couldn't backup {0}".format(full_name))
            if e.response["Error"]["Code"] == "NoSuchBucket":
                print("Bucket is not present.")
            _bck_error_array.add(region)


def _aws_s3_cp(s3, args, region, bucket_name, folder, src_file):
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
            _cp_error_array.add(region)
            if e.response["Error"]["Code"] == "NoSuchBucket":
                print("Bucket is not present.")

            raise e


def _create_s3_client(region):
    reg_credentials = [c for c in _credentials if c[0] == region]

    if reg_credentials:
        credential = reg_credentials[0]
        credential_region = credential[0]
        credential_endpoint = credential[1]
        credential_arn = credential[2]
        credential_external_id = credential[3]

        try:
            sts = boto3.client("sts", region_name=_main_region, endpoint_url=credential_endpoint)

            assumed_role_object = sts.assume_role(
                RoleArn=credential_arn,
                ExternalId=credential_external_id,
                RoleSessionName=credential_region + "upload_cfn_templates_sts_session",
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


def _get_bucket_name(args, region):
    return region + "-aws-parallelcluster" if not args.bucket else args.bucket


def _md5sum(cookbook_archive_file, md5sum_file):
    blocksize = 65536
    hasher = hashlib.md5()
    with open(cookbook_archive_file, "rb") as arch:
        buf = arch.read(blocksize)
        while len(buf) > 0:
            hasher.update(buf)
            buf = arch.read(blocksize)

    with open(md5sum_file, "w+") as md5:
        md5.write("{0}  {1}".format(hasher.hexdigest(), os.path.basename(cookbook_archive_file)))


def _parse_args():
    global _credentials
    global _main_region
    parser = argparse.ArgumentParser(description="Uploads cookbook to S3")

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
    parser.add_argument("--cookbook-archive-path", type=str, help="Cookbook archive path", required=True)
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

    args = parser.parse_args()
    if args.partition == "commercial":
        _main_region = "us-east-1"
    elif args.partition == "govcloud":
        _main_region = "us-gov-west-1"
    elif args.partition == "china":
        _main_region = "cn-north-1"
    else:
        print("Unsupported partition {0}".format(args.partition))
        exit(1)

    if args.credential:
        _credentials = [
            tuple(credential_tuple.strip().split(","))
            for credential_tuple in args.credential
            if credential_tuple.strip()
        ]

    if args.regions == "all":
        args.regions = _get_all_aws_regions(_main_region)
    else:
        args.regions = [x.strip() for x in args.regions.split(",")]

    args.unsupportedregions = [x.strip() for x in args.unsupportedregions.split(",")]

    # Purging regions
    args.regions = set(args.regions) - set(args.unsupportedregions)

    # Adds all opt-in regions
    for credential in _credentials:
        args.regions.add(credential[0])

    return args


def main():
    args = _parse_args()

    # Check if archive exists
    if not os.path.exists(args.cookbook_archive_path):
        print("Cookbook archive {0} not found".format(args.cookbook_archive_path))
        exit(1)

    base_name = os.path.splitext(os.path.basename(args.cookbook_archive_path))[0]
    _md5sum(args.cookbook_archive_path, "{0}.md5".format(base_name))

    for region in args.regions:
        s3 = _create_s3_client(region)
        bucket_name = _get_bucket_name(args, region)

        s3_key = _COOKBOOKS_DIR + "/" + base_name + ".tgz"
        print("Listing cookbook for region: {0}, bucket: {1}, key: {2}".format(region, bucket_name, s3_key))
        _aws_s3_ls(s3, region, bucket_name, s3_key)

    if len(_ls_error_array) > 0 and not args.override:
        print("We know the cookbook archives are already there, in this round we need to upload the .date files!")
        print("Failed to push cookbook, already present for regions: {0} ".format(" ".join(_ls_error_array)))
        exit(1)
    elif len(_ls_error_array) > 0 and args.override:
        print("Some or all of the cookbook archives are already there but OVERRIDE=true")

    for region in args.regions:
        s3 = _create_s3_client(region)
        bucket_name = _get_bucket_name(args, region)

        if args.override:
            print("Backup cookbook for region: {0}".format(region))
            _aws_s3_bck(s3, args, region, bucket_name, base_name + ".tgz")
            _aws_s3_bck(s3, args, region, bucket_name, base_name + ".md5")
            _aws_s3_bck(s3, args, region, bucket_name, base_name + ".tgz.date")

        print("Pushing cookbook for region: {0}".format(region))
        _aws_s3_cp(s3, args, region, bucket_name, _COOKBOOKS_DIR, args.cookbook_archive_path)
        _aws_s3_cp(s3, args, region, bucket_name, _COOKBOOKS_DIR, base_name + ".md5")

        if not args.dryrun:
            # Stores LastModified info into .tgz.date file and uploads it back to bucket
            with (open(base_name + ".tgz.date", "w+")) as f:
                response = s3.head_object(Bucket=bucket_name, Key=_COOKBOOKS_DIR + "/" + base_name + ".tgz")
                f.write(response.get("LastModified").strftime("%Y-%m-%d_%H-%M-%S"))

            _aws_s3_cp(s3, args, region, bucket_name, _COOKBOOKS_DIR, base_name + ".tgz.date")
        else:
            print("File {0}.{1} not stored to bucket {2} due to dryrun mode".format(base_name, "tgz.date", bucket_name))

    if len(_bck_error_array) > 0:
        print("Failed to backup cookbook for region ({0})".format(" ".join(_bck_error_array)))

    if len(_cp_error_array) > 0:
        print("Failed to push cookbook for region ({0})".format(" ".join(_cp_error_array)))
        exit(1)


if __name__ == "__main__":
    main()
