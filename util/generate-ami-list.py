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

import boto.ec2
import json
import argparse

owners = ["247102896272"]
distros = {"alinux": "amzn", "centos6": "centos6", "centos7": "centos7", "ubuntu1404": "ubuntu-1404", "ubuntu1604": "ubuntu-1604"}

amis_json_path = "amis.json"
amis_txt_path = "amis.txt"


def get_ami_list(date, version):
    amis_json = {}

    # get all regions
    regions = sorted(r.name for r in boto.ec2.regions())
    for region_name in regions:
        try:
            conn = boto.ec2.connect_to_region(region_name)
            images = conn.get_all_images(owners=owners, filters={"name": "cfncluster-" + version + "*" + date})

            amis = {}
            for image in images:
                for key, value in distros.items():
                    if value in image.name:
                        amis[key] = image.id

            ordered_amis = {}
            for key in sorted(amis):
                ordered_amis[key] = amis[key]

            amis_json[region_name] = ordered_amis

        except:
            pass

    return amis_json


def convert_json_to_txt(amis_json):
    amis_txt = ""
    for key, value in sorted(distros.items()):
        amis_txt += ("# " + key + "\n")

        regions = sorted(r.name for r in boto.ec2.regions())
        for region_name in regions:
            try:
                amis_txt += (region_name + ": " + amis_json[region_name][key] + "\n")
            except:
                pass

    return amis_txt


if __name__ == '__main__':
    # parse inputs
    parser = argparse.ArgumentParser(description='Get public cfncluster instances and generate a json and txt file')
    parser.add_argument('--version', type=str, help='release version e.g. 1.4.2', required=True)
    parser.add_argument('--date', type=str, help='release date [timestamp] e.g. 201801112350', required=True)
    args = parser.parse_args()

    # get ami list
    amis_json = get_ami_list(date=args.date, version=args.version)

    # write amis.json file
    amis_json_file = open(amis_json_path, "w")
    json.dump(amis_json, amis_json_file, indent=2, sort_keys=True)
    amis_json_file.close()

    # convert json to txt
    amis_txt = convert_json_to_txt(amis_json)

    # write amis.txt file
    amis_txt_file = open(amis_txt_path, "w")
    amis_txt_file.write("%s" % amis_txt)
    amis_txt_file.close()
