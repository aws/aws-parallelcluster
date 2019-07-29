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
# Search for AWS ParallelCluster AMIs and generate a list in json and txt format
#
# usage: ./generate-ami-list.py --version <aws-parallelcluster-version> --date <release-date>

import json
import re
import sys
from collections import OrderedDict

import argparse
import boto3
from botocore.exceptions import ClientError

distros = OrderedDict(
    [
        ("alinux", "amzn"),
        ("centos6", "centos6"),
        ("centos7", "centos7"),
        ("ubuntu1404", "ubuntu-1404"),
        ("ubuntu1604", "ubuntu-1604"),
    ]
)


def get_ami_list_from_file(regions, cfn_template_file):
    amis_json = {}

    with open(cfn_template_file) as cfn_file:
        # object_pairs_hook=OrderedDict allows to preserve input order
        cfn_data = json.load(cfn_file, object_pairs_hook=OrderedDict)

    current_amis = cfn_data.get("Mappings").get("AWSRegionOS2AMI")

    for region_name in regions:
        amis_json[region_name] = OrderedDict(sorted(current_amis.get(region_name).items()))
    return amis_json


def get_ami_list_from_ec2(main_region, regions, date, cookbook_git_ref, node_git_ref, version, owner, credentials):
    amis_json = {}

    for region_name in regions:
        filters = []
        if version and date:
            filters.append({"Name": "name", "Values": ["aws-parallelcluster-%s*%s" % (version, date)]})
        elif cookbook_git_ref and node_git_ref:
            filters.append({"Name": "tag:parallelcluster_cookbook_ref", "Values": ["%s" % cookbook_git_ref]})
            filters.append({"Name": "tag:parallelcluster_node_ref", "Values": ["%s" % node_git_ref]})
            filters.append({"Name": "name", "Values": ["aws-parallelcluster-*"]})
        else:
            print("Error: you can search for version and date or cookbook and node git reference")
            exit(1)

        images = get_images_ec2(filters, owner, region_name)
        populate_amis_json(amis_json, images, region_name)

        if main_region == region_name:
            for credential in credentials:
                credential_region = credential[0]
                images = get_images_ec2_credential(filters, main_region, credential)
                populate_amis_json(amis_json, images, credential_region)

    return amis_json


def populate_amis_json(amis_json, images, region_name):
    if images:
        amis = {}
        for image in images.get("Images"):
            for key, value in distros.items():
                if value in image.get("Name"):
                    amis[key] = image.get("ImageId")
        if len(amis) == 0:
            print("Warning: there are no AMIs in the selected region (%s)" % region_name)
        else:
            amis_json[region_name] = OrderedDict(sorted(amis.items()))


def get_images_ec2_credential(filters, main_region, credential):
    credential_region = credential[0]
    credential_endpoint = credential[1]
    credential_arn = credential[2]
    credential_external_id = credential[3]
    match = re.search(r"arn:aws:iam::(.*?):", credential_arn)
    credential_owner = match.group(1)

    try:
        sts = boto3.client("sts", region_name=main_region, endpoint_url=credential_endpoint)
        assumed_role_object = sts.assume_role(
            RoleArn=credential_arn,
            ExternalId=credential_external_id,
            RoleSessionName=credential_region + "generate_ami_list_sts_session",
        )
        aws_credentials = assumed_role_object["Credentials"]

        ec2 = boto3.client(
            "ec2",
            region_name=credential_region,
            aws_access_key_id=aws_credentials.get("AccessKeyId"),
            aws_secret_access_key=aws_credentials.get("SecretAccessKey"),
            aws_session_token=aws_credentials.get("SessionToken"),
        )

        images = ec2.describe_images(Owners=[credential_owner], Filters=filters)
        return images
    except ClientError:
        print("Warning: non authorized in region '{0}', skipping".format(credential_region))
        pass


def get_images_ec2(filters, owner, region_name):
    try:
        ec2 = boto3.client("ec2", region_name=region_name)
        images = ec2.describe_images(Owners=[owner], Filters=filters)
        return images
    except ClientError:
        print("Warning: non authorized in region '{0}', skipping".format(region_name))
        pass


def convert_json_to_txt(amis_json):
    amis_txt = ""
    for key, value in distros.items():
        amis_txt += "# " + key + "\n"
        for region, amis in amis_json.items():
            if key in amis:
                amis_txt += region + ": " + amis[key] + "\n"

    return amis_txt


def get_aws_regions_from_file(region_file):
    # Region file format
    # {
    #    "regions": [
    #        "cn-north-1",
    #        "cn-northwest-1"
    #    ]
    # }
    with open(region_file) as r_file:
        region_data = json.load(r_file)
    return sorted(r for r in region_data.get("regions"))


def get_all_aws_regions_from_ec2(region):
    ec2 = boto3.client("ec2", region_name=region)
    return sorted(r.get("RegionName") for r in ec2.describe_regions().get("Regions"))


def update_cfn_template(cfn_template_file, amis_to_update):
    with open(cfn_template_file) as cfn_file:
        # object_pairs_hook=OrderedDict allows to preserve input order
        cfn_data = json.load(cfn_file, object_pairs_hook=OrderedDict)
    # update id for new amis without removing regions that are not in the amis_to_update dict
    current_amis = cfn_data.get("Mappings").get("AWSRegionOS2AMI")
    current_amis.update(amis_to_update)
    # enforce alphabetical regions order
    ordered_amis = OrderedDict(sorted(current_amis.items()))
    cfn_data.get("Mappings")["AWSRegionOS2AMI"] = ordered_amis
    with open(cfn_template_file, "w") as cfn_file:
        # setting separators to (',', ': ') to avoid trailing spaces after commas
        json.dump(cfn_data, cfn_file, indent=2, separators=(",", ": "))
        # add new line at the end of the file
        cfn_file.write("\n")

    # returns the updated amis dict
    return ordered_amis


def update_amis_txt(amis_txt_file, amis):
    amis_txt = convert_json_to_txt(amis_json=amis)
    with open(amis_txt_file, "w") as f:
        f.write("%s" % amis_txt)


if __name__ == "__main__":
    # parse inputs
    parser = argparse.ArgumentParser(description="Get AWS ParallelCluster instances and generate a json and txt file")
    group1 = parser.add_argument_group("Retrieve instances from EC2 searching by version and date")
    group1.add_argument("--version", type=str, help="release version", required=False)
    group1.add_argument("--date", type=str, help="release date [timestamp] (e.g. 201801112350)", required=False)
    group2 = parser.add_argument_group("Retrieve instances from EC2 searching by cookbook and node git reference")
    group2.add_argument("--cookbook-git-ref", type=str, help="cookbook git hash reference", required=False)
    group2.add_argument("--node-git-ref", type=str, help="node git hash reference", required=False)
    group2.add_argument(
        "--credential",
        type=str,
        action="append",
        help="STS credential endpoint, in the format <region>,<endpoint>,<ARN>,<externalId>. Could be specified multiple times",
        required=False,
    )
    group3 = parser.add_argument_group("Retrieve instances from local cfn template for given regions")
    group3.add_argument("--json-template", type=str, help="path to input json cloudformation template", required=False)
    group3.add_argument(
        "--json-regions", type=str, help="path to input json file containing the regions", required=False
    )
    parser.add_argument("--txt-file", type=str, help="txt output file path", required=False, default="amis.txt")
    parser.add_argument("--partition", type=str, help="commercial | china | govcloud", required=True)
    parser.add_argument(
        "--cloudformation-template",
        type=str,
        help="path to output cloudfomation template",
        required=False,
        default="cloudformation/aws-parallelcluster.cfn.json",
    )
    args = parser.parse_args()

    if args.partition == "commercial":
        account_id = "247102896272"
        region = "us-east-1"
    elif args.partition == "govcloud":
        account_id = "124026578433"
        region = "us-gov-west-1"
    elif args.partition == "china":
        account_id = "036028979999"
        region = "cn-north-1"
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

    if (args.version and args.date) or (args.cookbook_git_ref and args.node_git_ref):
        regions = get_all_aws_regions_from_ec2(region)
        amis_dict = get_ami_list_from_ec2(
            main_region=region,
            regions=regions,
            date=args.date,
            cookbook_git_ref=args.cookbook_git_ref,
            node_git_ref=args.node_git_ref,
            version=args.version,
            owner=account_id,
            credentials=credentials,
        )
    else:
        regions = get_aws_regions_from_file(args.json_regions)
        amis_dict = get_ami_list_from_file(regions, args.json_template)

    cfn_amis = update_cfn_template(cfn_template_file=args.cloudformation_template, amis_to_update=amis_dict)
    update_amis_txt(amis_txt_file=args.txt_file, amis=cfn_amis)
