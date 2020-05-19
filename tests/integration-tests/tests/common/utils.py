# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import json
import logging

import boto3
from retrying import retry

OS_TO_OFFICIAL_AMI_NAME_OWNER_MAP = {
    "alinux": {"name": "amzn-ami-hvm-*.*.*.*-*-gp2", "owners": ["amazon"]},
    "alinux2": {"name": "amzn2-ami-hvm-*.*.*.*-*-gp2", "owners": ["amazon"]},
    "centos7": {"name": "CentOS Linux 7 * HVM EBS ENA *", "owners": ["410186602215"]},
    "ubuntu1404": {
        "name": "ubuntu/images/hvm-ssd/ubuntu-trusty-14.04-*-server-*",
        "owners": ["099720109477", "513442679011", "837727238323"],
    },
    "ubuntu1604": {
        "name": "ubuntu/images/hvm-ssd/ubuntu-xenial-16.04-*-server-*",
        "owners": ["099720109477", "513442679011", "837727238323"],
    },
    "ubuntu1804": {
        "name": "ubuntu/images/hvm-ssd/ubuntu-bionic-18.04-*-server-*",
        "owners": ["099720109477", "513442679011", "837727238323"],
    },
}

OS_TO_REMARKABLE_AMI_NAME_OWNER_MAP = {
    "alinux": {"name": "Deep Learning Base AMI (Amazon Linux)*", "owners": ["amazon"]},
    "alinux2": {"name": "Deep Learning Base AMI (Amazon Linux 2)*", "owners": ["amazon"]},
    "centos7": {"name": "FPGA Developer AMI*", "owners": ["679593333241"]},
    "ubuntu1604": {"name": "Deep Learning Base AMI (Ubuntu 16.04)*", "owners": ["amazon"]},
    "ubuntu1804": {"name": "Deep Learning Base AMI (Ubuntu 18.04)*", "owners": ["amazon"]},
}

AMI_TYPE_DICT = {
    "official": OS_TO_OFFICIAL_AMI_NAME_OWNER_MAP,
    "remarkable": OS_TO_REMARKABLE_AMI_NAME_OWNER_MAP,
}


def retrieve_latest_ami(region, os, ami_type="official", architecture="x86_64"):
    ec2_client = boto3.client("ec2", region_name=region)
    response = ec2_client.describe_images(
        Filters=[
            {"Name": "name", "Values": [AMI_TYPE_DICT[ami_type][os]["name"]]},
            {"Name": "architecture", "Values": [architecture]},
        ],
        Owners=AMI_TYPE_DICT[ami_type][os]["owners"],
    )
    # Sort on Creation date Desc
    amis = sorted(response["Images"], key=lambda x: x["CreationDate"], reverse=True)
    return amis[0]["ImageId"]


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def fetch_instance_slots(region, instance_type, slots="vcpus"):
    bucket_name = "{0}-aws-parallelcluster".format(region)
    try:
        s3 = boto3.resource("s3", region_name=region)
        instances_file_content = s3.Object(bucket_name, "instances/instances.json").get()["Body"].read()
        instances = json.loads(instances_file_content)
        return int(instances[instance_type][slots])
    except Exception as e:
        logging.critical(
            "Could not load instance mapping file from S3 bucket {0}. Failed with exception: {1}".format(bucket_name, e)
        )
        raise
