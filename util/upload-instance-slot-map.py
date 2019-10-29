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


def dump_instances(instance_details, region, aws_credentials=None):
    """
    Get instance information from pricing file and dump to instances.json
    """
    # Added exception block to check if pricing information is a valid JSON file
    try:
        with open(instance_details) as data_file:
            data = json.load(data_file)
    except json.JSONDecodeError as e:
        print("Error when parsing pricing information: {0}".format(e.msg))
        raise

    instances = {}
    for sku, product in data.get("products").items():
        if "Compute Instance" in product.get("productFamily"):
            instance = product.get("attributes")
            instances[instance.get("instanceType")] = {"vcpus": instance.get("vcpu")}
            # Sample memory input: {"memory" : "30 GiB"}
            instances[instance.get("instanceType")]["memory"] = instance.get("memory")
            # Adding instance's gpu information to instances.json
            if "gpu" in instance:
                instances[instance.get("instanceType")]["gpu"] = instance.get("gpu")

    # Check if all info from old instances.json is included in the new instances.json
    validate_against_old_version(instances, region, aws_credentials)

    print(json.dumps(instances))
    json.dump(instances, open("instances.json", "w"))


def validate_against_old_version(instances_info, region, aws_credentials=None):
    """
    Validate that old instances information are all contained in the new version
    """
    old_instances_info = get_old_instances_info(region, aws_credentials)
    print("Old instances.json:\n{0}".format(old_instances_info))
    print("New instances.json:\n{0}".format(instances_info))
    for instance_type in old_instances_info:
        if instance_type not in instances_info:
            _fail("new file does not contain {0} instance type!".format(instance_type))
        for resource in old_instances_info[instance_type]:
            if resource not in instances_info[instance_type]:
                _fail("new file does not contain {0} resource for {1} instance type!".format(resource, instance_type))
            if old_instances_info[instance_type][resource] != instances_info[instance_type][resource]:
                _fail(
                    "{0}:{1} value is different from previous version! New value: {2}, previous value: {3}!".format(
                        instance_type,
                        resource,
                        instances_info[instance_type][resource],
                        old_instances_info[instance_type][resource],
                    )
                )


def get_all_aws_regions(region):
    """Return all AWS regions"""
    ec2 = boto3.client("ec2", region_name=region)
    return sorted(r.get("RegionName") for r in ec2.describe_regions().get("Regions"))


def get_old_instances_info(region, aws_credentials=None):
    """
    Retrieve and parse old instances.json from aws-parallelcluster S3 bucket
    """
    bucket_name = "{0}-aws-parallelcluster".format(region)
    print(bucket_name)
    s3 = return_s3_object(region, aws_credentials, bucket_name)
    old_instances_file_content = s3.Object(bucket_name, "instances/instances.json").get()["Body"].read()
    try:
        old_instances_info = json.loads(old_instances_file_content)
    except json.JSONDecodeError as e:
        print("Error when parsing information from old instances.json: {0}".format(e.msg))
        raise
    return old_instances_info


def push_to_s3(region, aws_credentials=None):
    """Push instances.json to S3"""
    bucket_name = "{0}-aws-parallelcluster".format(region)
    print(bucket_name)
    s3 = return_s3_object(region, aws_credentials, bucket_name)
    bucket = s3.Bucket(bucket_name)
    bucket.upload_file("instances.json", "instances/instances.json")
    object_acl = s3.ObjectAcl(bucket_name, "instances/instances.json")
    object_acl.put(ACL="public-read")


def return_s3_object(region, aws_credentials, bucket_name):
    """Return an S3 object"""
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
        return s3
    except ClientError as e:
        # If a client error is thrown, then check that it was a 404 error.
        # If it was a 404 error, then the bucket does not exist.
        error_code = int(e.response["Error"]["Code"])
        if error_code == 404:
            print("Bucket {0} does not exist".format(bucket_name))
            return
        raise


def upload(regions, main_region, credentials):
    """Push instances.json to all regions"""
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


def _fail(msg):
    """Print old and new instances.json and error message then exit."""
    print("ERROR: {0}".format(msg))
    sys.exit(1)


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
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="If deploy is false, we will perform a dryrun and instances.json will not be pushed to buckets",
        default=False,
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
        print("Unsupported partition {0}".format(args.partition))
        sys.exit(1)

    credentials = []
    if args.credential:
        credentials = [
            tuple(credential_tuple.strip().split(","))
            for credential_tuple in args.credential
            if credential_tuple.strip()
        ]

    dump_instances(args.instance_details, main_region, credentials)

    regions = get_all_aws_regions(main_region)

    if args.deploy:
        print("Pushing instances.json to S3...")
        upload(regions, main_region, credentials)
