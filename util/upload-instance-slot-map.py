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


def push_to_s3(region, aws_credentials=None):
    bucket_name = region + "-aws-parallelcluster"
    print(bucket_name)
    try:
        if aws_credentials:
            s3 = boto3.resource(
                "s3",
                region_name=region,
                aws_access_key_id=aws_credentials.get("AccessKeyId"),
                aws_secret_access_key=aws_credentials.get("SecretAccessKey"),
                aws_session_token=aws_credentials.get("SessionToken"),
            )
        else:
            s3 = boto3.resource("s3", region_name=region)
        s3.meta.client.head_bucket(Bucket=bucket_name)
    except ClientError as e:
        # If a client error is thrown, then check that it was a 404 error.
        # If it was a 404 error, then the bucket does not exist.
        error_code = int(e.response["Error"]["Code"])
        if error_code == 404:
            print("Bucket %s does not exist", bucket_name)
            return
        raise

    bucket = s3.Bucket(bucket_name)
    bucket.upload_file("instances.json", "instances/instances.json")
    object_acl = s3.ObjectAcl(bucket_name, "instances/instances.json")
    object_acl.put(ACL="public-read")


def upload(regions, main_region, credentials):
    for region in regions:
        push_to_s3(region)

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
                        RoleSessionName=credential_region + "upload_instance_slot_map_sts_session",
                    )
                    aws_credentials = assumed_role_object["Credentials"]

                    push_to_s3(credential_region, aws_credentials)
                except ClientError:
                    print("Warning: non authorized in region '{0}', skipping".format(credential_region))
                    pass


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
    parser.add_argument(
        "--credential",
        type=str,
        action="append",
        help="STS credential endpoint, in the format <region>,<endpoint>,<ARN>,<externalId>. Could be specified multiple times",
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

    dump_instances(args.instance_details)

    regions = get_all_aws_regions(main_region)

    upload(regions, main_region, credentials)
