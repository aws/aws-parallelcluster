#!/usr/bin/python
#
# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
# Search for AWS ParallelCluster public AMIs and generate a list in json and txt format
#
# usage: ./batch-instance-whitelist.py --regions <'all' or comma seperated list> --bucket <bucket_name, defaults to [region-aws-parallelcluster]>

import json
import re
import sys

import argparse
import boto3
from botocore.exceptions import ClientError

# regions unsupported by aws batch
UNSUPPORTED_REGIONS = set(
    ["ap-northeast-3", "eu-north-1", "cn-north-1", "cn-northwest-1", "us-gov-east-1", "us-gov-west-1"]
)


def get_all_aws_regions(partition):
    if partition == "commercial":
        region = "us-east-1"
    elif partition == "govcloud":
        region = "us-gov-west-1"
    elif partition == "china":
        region = "cn-north-1"
    else:
        print("Unsupported partition %s" % partition)
        sys.exit(1)

    ec2 = boto3.client("ec2", region_name=region)
    return set(sorted(r.get("RegionName") for r in ec2.describe_regions().get("Regions"))) - UNSUPPORTED_REGIONS


def get_instance_whitelist(args, region):

    # try to create a dummy compute environmment
    batch_client = boto3.client("batch", region_name=region)

    try:
        response = batch_client.create_compute_environment(
            computeEnvironmentName="dummy",
            type="MANAGED",
            computeResources={
                "type": "EC2",
                "minvCpus": 0,
                "maxvCpus": 0,
                "instanceTypes": ["p8.84xlarge"],  # instance type must not exist
                "subnets": ["subnet-12345"],  # security group, subnet and role aren't checked
                "securityGroupIds": ["sg-12345"],
                "instanceRole": "ecsInstanceRole",
            },
            serviceRole="AWSBatchServiceRole",
        )
    except ClientError as e:
        match = re.search(r"be one of \[(.*)\]", e.response.get("Error").get("Message"))
        if match:
            instances = match.groups(0)[0].split(", ")
        else:
            print("Invalid Error message, could not determine instance whitelist: %s" % e)
            sys.exit(1)

    return instances


def upload_to_s3(args, region, instances):

    s3_client = boto3.resource("s3", region_name=region)

    bucket = args.bucket if args.bucket else "%s-aws-parallelcluster" % region
    key = "instances/batch_instances.json"

    if args.dryrun == "true":
        print(instances)
        print("Skipping upload to s3://%s/%s" % (bucket, key))
        return

    try:
        object = s3_client.Object(bucket, key)
        response = object.put(Body=json.dumps(instances), ACL="public-read")

        if response.get("ResponseMetadata").get("HTTPStatusCode") == 200:
            print("Successfully uploaded to s3://%s/%s" % (bucket, key))
    except ClientError as e:
        print("Couldn't upload %s to bucket s3://%s/%s" % (instances, bucket, key))
        raise e

    return response


def main(args):
    # For all regions
    for region in args.regions:
        instances = get_instance_whitelist(args, region)
        response = upload_to_s3(args, region, instances)


if __name__ == "__main__":
    # parse inputs
    parser = argparse.ArgumentParser(description="Generate a whitelist of batch instance types.")
    parser.add_argument("--partition", type=str, help="commercial | china | govcloud", required=True)
    parser.add_argument(
        "--regions",
        type=str,
        help='Valid Regions, can include "all", or comma seperated list of regions',
        required=True,
    )
    parser.add_argument(
        "--bucket", type=str, help="Bucket to upload too, defaults to [region]-aws-parallelcluster", required=False
    )
    parser.add_argument("--dryrun", type=str, help="Doesn't push anything to S3, just outputs", required=True)
    args = parser.parse_args()

    if args.regions == "all":
        args.regions = get_all_aws_regions(args.partition)
    else:
        args.regions = args.regions.split(",")

    main(args)
