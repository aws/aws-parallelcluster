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
import logging
import sys

import boto3
from botocore.exceptions import ClientError
from retrying import retry
from utils import get_instance_info

from pcluster.utils import get_installed_version

LOGGER = logging.getLogger(__name__)

OS_TO_OFFICIAL_AMI_NAME_OWNER_MAP = {
    "alinux": {"name": "amzn-ami-hvm-*.*.*.*-*-gp2", "owners": ["amazon"]},
    "alinux2": {"name": "amzn2-ami-hvm-*.*.*.*-*-gp2", "owners": ["amazon"]},
    "centos7": {"name": "CentOS 7.* *", "owners": ["125523088429"]},
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

# Remarkable AMIs are latest deep learning base AMI and FPGA developer AMI without pcluster infrastructure
OS_TO_REMARKABLE_AMI_NAME_OWNER_MAP = {
    "alinux": {"name": "Deep Learning Base AMI (Amazon Linux)*", "owners": ["amazon"]},
    "alinux2": {"name": "Deep Learning Base AMI (Amazon Linux 2)*", "owners": ["amazon"]},
    "centos7": {"name": "FPGA Developer AMI*", "owners": ["679593333241"]},
    "ubuntu1604": {"name": "Deep Learning Base AMI (Ubuntu 16.04)*", "owners": ["amazon"]},
    "ubuntu1804": {"name": "Deep Learning Base AMI (Ubuntu 18.04)*", "owners": ["amazon"]},
}

# Pcluster AMIs are latest ParallelCluster official AMIs that align with cli version
OS_TO_PCLUSTER_AMI_NAME_OWNER_MAP = {
    "alinux": {"name": "amzn-hvm-x86_64-*", "owners": ["amazon"]},
    "alinux2": {"name": "amzn2-hvm-*-*", "owners": ["amazon"]},
    "centos6": {"name": "centos6-hvm-x86_64-*", "owners": ["amazon"]},
    "centos7": {"name": "centos7-hvm-x86_64-*", "owners": ["amazon"]},
    "ubuntu1604": {"name": "ubuntu-1604-lts-hvm-x86_64-*", "owners": ["amazon"]},
    "ubuntu1804": {"name": "ubuntu-1804-lts-hvm-*-*", "owners": ["amazon"]},
}

AMI_TYPE_DICT = {
    "official": OS_TO_OFFICIAL_AMI_NAME_OWNER_MAP,
    "remarkable": OS_TO_REMARKABLE_AMI_NAME_OWNER_MAP,
    "pcluster": OS_TO_PCLUSTER_AMI_NAME_OWNER_MAP,
}


def retrieve_latest_ami(region, os, ami_type="official", architecture="x86_64"):
    try:
        if ami_type == "pcluster":
            ami_name = "aws-parallelcluster-{version}-{ami_name}".format(
                version=get_installed_version(), ami_name=AMI_TYPE_DICT.get(ami_type).get(os).get("name")
            )
        else:
            ami_name = AMI_TYPE_DICT.get(ami_type).get(os).get("name")
        response = boto3.client("ec2", region_name=region).describe_images(
            Filters=[{"Name": "name", "Values": [ami_name]}, {"Name": "architecture", "Values": [architecture]}],
            Owners=AMI_TYPE_DICT.get(ami_type).get(os).get("owners"),
        )
        # Sort on Creation date Desc
        amis = sorted(response.get("Images", []), key=lambda x: x["CreationDate"], reverse=True)
        return amis[0]["ImageId"]
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.exit(1)
    except AttributeError as e:
        LOGGER.critical("Error no attribute {0} in dict: {1}".format(os, e))
        sys.exit(1)
    except IndexError as e:
        LOGGER.critical("Error no ami retrieved: {0}".format(e))
        sys.exit(1)


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def fetch_instance_slots(region, instance_type):
    return get_instance_info(instance_type, region).get("VCpuInfo").get("DefaultVCpus")
