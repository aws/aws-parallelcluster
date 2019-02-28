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
# Upload instance slot map
#
# usage: ./upload-instance-slot-map.py --partition <partition> [--instance-details <instance-details.json>]

import json
import sys

import argparse
import boto3
from botocore.exceptions import ClientError


def dump_instances(instance_details):
    with open(instance_details) as data_file:
        data = json.load(data_file)
    instances = {}
    for sku, product in data.get("products").iteritems():
        if product.get("productFamily") == "Compute Instance":
            instance = product.get("attributes")
            instances[instance.get("instanceType")] = {"vcpus": instance.get("vcpu")}
    print(json.dumps(instances))
    json.dump(instances, open("instances.json", "w"))


def get_all_aws_regions(region):
    ec2 = boto3.client("ec2", region_name=region)
    return sorted(r.get("RegionName") for r in ec2.describe_regions().get("Regions"))


def upload(regions):
    for region in regions:
        bucket_name = region + "-aws-parallelcluster"
        print(bucket_name)
        try:
            s3 = boto3.resource("s3", region_name=region)
            s3.meta.client.head_bucket(Bucket=bucket_name)
        except ClientError as e:
            # If a client error is thrown, then check that it was a 404 error.
            # If it was a 404 error, then the bucket does not exist.
            error_code = int(e.response["Error"]["Code"])
            if error_code == 404:
                print("Bucket %s does not exist", bucket_name)
                continue
            raise

        bucket = s3.Bucket(bucket_name)
        bucket.upload_file("instances.json", "instances/instances.json")
        object_acl = s3.ObjectAcl(bucket_name, "instances/instances.json")
        object_acl.put(ACL="public-read")


if __name__ == "__main__":
    # parse inputs
    parser = argparse.ArgumentParser(description="Upload instance slot map")

    parser.add_argument("--partition", type=str, help="commercial | china | govcloud", required=True)
    parser.add_argument(
        "--instance-details",
        type=str,
        help="path to cloudfomation template",
        required=False,
        default="instance-details.json",
    )
    args = parser.parse_args()

    if args.partition == "commercial":
        region = "us-east-1"
    elif args.partition == "govcloud":
        region = "us-gov-west-1"
    elif args.partition == "china":
        region = "cn-north-1"
    else:
        print("Unsupported partition %s" % args.partition)
        sys.exit(1)

    dump_instances(args.instance_details)

    regions = get_all_aws_regions(region)

    upload(regions)
