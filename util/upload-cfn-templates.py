#!/usr/bin/python
# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import os
import sys
from glob import glob

import argparse
import boto3
import pkg_resources
from botocore.exceptions import ClientError


def get_all_aws_regions(region):
    ec2 = boto3.client("ec2", region_name=region)
    return set(sorted(r.get("RegionName") for r in ec2.describe_regions().get("Regions")))


def get_template_extension(templates_dir, template_name):
    matching_files = glob("{}{}.*".format(templates_dir, template_name))
    if len(matching_files) != 1:
        raise Exception(
            "Found 0 or multiple matching files for template name {}: {}".format(template_name, matching_files)
        )
    file_name = os.path.basename(matching_files[0])
    extension = file_name.split(".cfn.")[-1]
    if extension not in {"json", "yaml"}:
        raise Exception("Found invalid extension for template {}: {}".format(template_name, extension))
    return ".cfn." + extension


def put_object_to_s3(s3_client, bucket, key, region, data, template_name):
    try:
        object = s3_client.Object(bucket, key)
        response = object.put(Body=data, ACL="public-read")
        if response.get("ResponseMetadata").get("HTTPStatusCode") == 200:
            print("Successfully uploaded %s to s3://%s/%s" % (template_name, bucket, key))
    except ClientError as e:
        if args.createifnobucket and e.response["Error"]["Code"] == "NoSuchBucket":
            print("No bucket, creating now: ")
            if region == "us-east-1":
                s3_client.create_bucket(Bucket=bucket)
            else:
                s3_client.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": region})
            s3_client.BucketVersioning(bucket).enable()
            print("Created %s bucket. Bucket versioning is enabled, " "please enable bucket logging manually." % bucket)
            b = s3_client.Bucket(bucket)
            res = b.put_object(Body=data, ACL="public-read", Key=key)
            print(res)
        else:
            print("Couldn't upload %s to bucket s3://%s/%s" % (template_name, bucket, key))
            if e.response["Error"]["Code"] == "NoSuchBucket":
                print("Bucket is not present.")
            else:
                raise e
        pass


def upload_to_s3(args, region, aws_credentials=None):
    if aws_credentials:
        s3_client = boto3.resource(
            "s3",
            region_name=region,
            aws_access_key_id=aws_credentials.get("AccessKeyId"),
            aws_secret_access_key=aws_credentials.get("SecretAccessKey"),
            aws_session_token=aws_credentials.get("SessionToken"),
        )
    else:
        s3_client = boto3.resource("s3", region_name=region)

    if args.bucket:
        buckets = args.bucket.split(",")
    else:
        buckets = ["%s-aws-parallelcluster" % region]
    key_path = "templates/"
    template_paths = "cloudformation/"

    for t in args.templates:
        template_ext = get_template_extension(template_paths, t)
        template_name = "{dir}{name}{extension}".format(dir=template_paths, name=t, extension=template_ext)
        key = "{key_path}{name}-{version}{extension}".format(
            key_path=key_path, name=t, version=args.version, extension=template_ext
        )
        data = open(template_name, "rb")
        for bucket in buckets:
            try:
                if aws_credentials:
                    s3 = boto3.client(
                        "s3",
                        region_name=region,
                        aws_access_key_id=aws_credentials.get("AccessKeyId"),
                        aws_secret_access_key=aws_credentials.get("SecretAccessKey"),
                        aws_session_token=aws_credentials.get("SessionToken"),
                    )
                else:
                    s3 = boto3.client("s3", region_name=region)

                s3.head_object(Bucket=bucket, Key=key)
                print("Warning: %s already exist in bucket %s" % (key, bucket))
                exist = True
            except ClientError:
                exist = False
                pass

            if (exist and args.override and not args.dryrun) or (not exist and not args.dryrun):
                put_object_to_s3(s3_client, bucket, key, region, data, template_name)
            else:
                print(
                    "Not uploading %s to bucket %s, object exists %s, override is %s, dryrun is %s"
                    % (template_name, bucket, exist, args.override, args.dryrun)
                )


def main(main_region, args):
    # For all regions
    for region in args.regions:
        upload_to_s3(args, region)

        if main_region == region:
            for credential in credentials:
                credential_region = credential[0]
                credential_endpoint = credential[1]
                credential_arn = credential[2]
                credential_external_id = credential[3]

                try:
                    sts = boto3.client("sts", region_name=main_region, endpoint_url=credential_endpoint)
                    assumed_role_object = sts.assume_role(
                        RoleArn=credential_arn,
                        ExternalId=credential_external_id,
                        RoleSessionName=credential_region + "upload_cfn_templates_sts_session",
                    )
                    aws_credentials = assumed_role_object["Credentials"]

                    upload_to_s3(args, credential_region, aws_credentials)

                except ClientError:
                    print("Warning: non authorized in region '{0}', skipping".format(credential_region))
                    pass


if __name__ == "__main__":
    # parse inputs
    parser = argparse.ArgumentParser(description="Upload extra templates under /cloudformation")
    parser.add_argument("--partition", type=str, help="commercial | china | govcloud", required=True)
    parser.add_argument(
        "--regions",
        type=str,
        help='Valid Regions, can include "all", or comma separated list of regions',
        required=True,
    )
    parser.add_argument(
        "--credential",
        type=str,
        action="append",
        help="STS credential endpoint, in the format <region>,<endpoint>,<ARN>,<externalId>."
        "Could be specified multiple times",
        required=False,
    )
    parser.add_argument(
        "--templates", type=str, help="Template filenames, leave out '.cfn.json', comma separated list", required=True
    )
    parser.add_argument(
        "--bucket",
        type=str,
        help="Buckets to upload to, defaults to [region]-aws-parallelcluster, comma separated list",
        required=False,
    )
    parser.add_argument(
        "--dryrun", action="store_true", help="Doesn't push anything to S3, just outputs", default=False, required=False
    )
    parser.add_argument(
        "--override",
        action="store_true",
        help="If override is false, the file will not be pushed if it already exists in the bucket",
        default=False,
        required=False,
    )
    parser.add_argument(
        "--createifnobucket",
        action="store_true",
        help="Create S3 bucket if it does not exist",
        default=False,
        required=False,
    )
    parser.add_argument(
        "--unsupportedregions", type=str, help="Unsupported regions, comma separated", default="", required=False
    )
    parser.add_argument(
        "--version",
        type=str,
        help="If not specified it's retrieved from the package version",
        default="",
        required=False,
    )
    args = parser.parse_args()

    if args.partition == "commercial":
        main_region = "us-east-1"
    elif args.partition == "govcloud":
        main_region = "us-gov-west-1"
    elif args.partition == "china":
        main_region = "cn-north-1"
    else:
        print("Unsupported partition %s" % args.partition)
        sys.exit(1)

    credentials = []
    if args.credential:
        credentials = [
            tuple(credential_tuple.strip().split(","))
            for credential_tuple in args.credential
            if credential_tuple.strip()
        ]

    if not args.version:
        args.version = pkg_resources.get_distribution("aws-parallelcluster").version

    if args.regions == "all":
        args.regions = get_all_aws_regions(main_region)
    else:
        args.regions = args.regions.split(",")
    args.regions = set(args.regions) - set(args.unsupportedregions.split(","))

    args.templates = args.templates.split(",")

    main(main_region, args)
