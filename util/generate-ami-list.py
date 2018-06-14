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
# Search for CfnCluster public AMIs and generate a list in json and txt format
#
# usage: ./generate-ami-list.py --version <cfncluster-version> --date <release-date>

import boto3
from botocore.exceptions import ClientError
import argparse
import json
import sys
from collections import OrderedDict


owners = ["247102896272"]
distros = OrderedDict([("alinux", "amzn"), ("centos6", "centos6"), ("centos7", "centos7"), ("ubuntu1404", "ubuntu-1404"), ("ubuntu1604", "ubuntu-1604")])


def get_ami_list(regions, date, version):
    amis_json = {}

    for region_name in regions:
        try:
            ec2 = boto3.client('ec2', region_name=region_name)
            images = ec2.describe_images(Owners=owners, Filters=[{'Name': 'name', "Values": ["cfncluster-%s*%s" % (version, date)]}])

            amis = OrderedDict()
            for image in images.get('Images'):
                for key, value in distros.items():
                    if value in image.get('Name'):
                        amis[key] = image.get('ImageId')

            if len(amis) == 0:
                print("Warning: there are no AMIs in the selected region (%s)" % region_name)
            else:
                amis_json[region_name] = amis
        except ClientError:
            # skip regions on which we are not authorized (cn-north-1 and us-gov-west-1)
            pass

    return amis_json


def convert_json_to_txt(regions, amis_json):
    amis_txt = ""
    for key, value in distros.items():
        amis_txt += ("# " + key + "\n")
        for region_name in regions:
            try:
                amis_txt += (region_name + ": " + amis_json[region_name][key] + "\n")
            except KeyError:
                # skip for regions without AMIs
                pass

    return amis_txt


if __name__ == '__main__':
    # parse inputs
    parser = argparse.ArgumentParser(description='Get public cfncluster instances and generate a json and txt file')
    parser.add_argument('--version', type=str, help='release version (e.g. 1.5.0)', required=True)
    parser.add_argument('--date', type=str, help='release date [timestamp] (e.g. 201801112350)', required=True)
    parser.add_argument('--json-file', type=str, help='json output file path', required=False, default="amis.json")
    parser.add_argument('--txt-file', type=str, help='txt output file path', required=False, default="amis.txt")
    args = parser.parse_args()

    # get all regions
    ec2 = boto3.client('ec2')
    regions = sorted(r.get('RegionName') for r in ec2.describe_regions().get('Regions'))

    # get ami list
    amis_json = get_ami_list(regions=regions, date=args.date, version=args.version)

    # write amis.json file
    amis_json_file = open(args.json_file, "w")
    json.dump(amis_json, amis_json_file, indent=2, sort_keys=True)
    amis_json_file.close()

    # convert json to txt
    amis_txt = convert_json_to_txt(regions=regions, amis_json=amis_json)

    # write amis.txt file
    amis_txt_file = open(args.txt_file, "w")
    amis_txt_file.write("%s" % amis_txt)
    amis_txt_file.close()
