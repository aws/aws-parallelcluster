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
from botocore.exceptions import ClientError, EndpointConnectionError


def get_all_aws_regions(region):
    ec2 = boto3.client("ec2", region_name=region)
    return set(sorted(r.get("RegionName") for r in ec2.describe_regions().get("Regions")))


def get_batch_instance_whitelist(region, aws_credentials=None):
    instances = []
    # try to create a dummy compute environmment
    if aws_credentials:
        batch_client = boto3.client(
            "batch",
            region_name=region,
            aws_access_key_id=aws_credentials.get("AccessKeyId"),
            aws_secret_access_key=aws_credentials.get("SecretAccessKey"),
            aws_session_token=aws_credentials.get("SessionToken"),
        )
    else:
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
    except EndpointConnectionError as e:
        print("Could not connect to the batch endpoint for region " + region)
        pass

    return instances


def upload_to_s3(args, region, instances, key, aws_credentials=None):
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

    bucket = args.bucket if args.bucket else "%s-aws-parallelcluster" % region

    if args.dryrun == "true":
        print("S3 object content is: " + json.dumps(instances))
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


def main(main_region, args):
    # For all regions
    for region in args.regions:
        push_whitelist(args, region)

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

                    push_whitelist(args, credential_region, aws_credentials)

                except ClientError:
                    print("Warning: non authorized in region '{0}', skipping".format(credential_region))
                    pass


def push_whitelist(args, region, aws_credentials=None):
    batch_instances = get_batch_instance_whitelist(region, aws_credentials)
    if args.efa:
        efa_instances = args.efa.split(",")
        instances = {"Features": {"efa": {"instances": efa_instances}, "batch": {"instances": batch_instances}}}
        upload_to_s3(args, region, instances, "features/feature_whitelist.json", aws_credentials)
    else:
        upload_to_s3(args, region, batch_instances, "instances/batch_instances.json", aws_credentials)


if __name__ == "__main__":
    # parse inputs
    parser = argparse.ArgumentParser(description="Generate a whitelist of instance types per region.")
    parser.add_argument("--partition", type=str, help="commercial | china | govcloud", required=True)
    parser.add_argument(
        "--regions",
        type=str,
        help='Valid Regions, can include "all", or comma seperated list of regions',
        required=True,
    )
    parser.add_argument(
        "--credential",
        type=str,
        action="append",
        help="STS credential endpoint, in the format <region>,<endpoint>,<ARN>,<externalId>. Could be specified multiple times",
        required=False,
    )
    parser.add_argument(
        "--bucket", type=str, help="Bucket to upload too, defaults to [region]-aws-parallelcluster", required=False
    )
    parser.add_argument("--efa", type=str, help="Comma separated list of instances supported by EFA", required=False)
    parser.add_argument("--dryrun", type=str, help="Doesn't push anything to S3, just outputs", required=True)
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

    if args.regions == "all":
        args.regions = get_all_aws_regions(main_region)
    else:
        args.regions = args.regions.split(",")

    main(main_region, args)
