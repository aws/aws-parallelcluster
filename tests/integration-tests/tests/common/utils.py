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
import random
import string
import time

import boto3
import pkg_resources
from assertpy import assert_that
from botocore.exceptions import ClientError
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import seconds
from utils import get_instance_info

LOGGER = logging.getLogger(__name__)

OS_TO_OFFICIAL_AMI_NAME_OWNER_MAP = {
    "alinux2": {"name": "amzn2-ami-hvm-*.*.*.*-*-gp2", "owners": ["amazon"]},
    "centos7": {"name": "CentOS 7.*", "owners": ["125523088429"]},
    "ubuntu1804": {
        "name": "ubuntu/images/hvm-ssd/ubuntu-bionic-18.04-*-server-*",
        "owners": ["099720109477", "513442679011", "837727238323"],
    },
    "ubuntu2004": {
        "name": "ubuntu/images/hvm-ssd/ubuntu-focal-20.04-*-server-*",
        "owners": ["099720109477"],
    },
}

# Remarkable AMIs are latest deep learning base AMI and FPGA developer AMI without pcluster infrastructure
OS_TO_REMARKABLE_AMI_NAME_OWNER_MAP = {
    "alinux2": {"name": "Deep Learning Base AMI (Amazon Linux 2)*", "owners": ["amazon"]},
    "centos7": {"name": "FPGA Developer AMI*", "owners": ["679593333241"]},
    "ubuntu1804": {"name": "Deep Learning Base AMI (Ubuntu 18.04)*", "owners": ["amazon"]},
}

# Get official pcluster AMIs or get from dev account
PCLUSTER_AMI_OWNERS = ["amazon", "self"]
# Pcluster AMIs are latest ParallelCluster official AMIs that align with cli version
OS_TO_PCLUSTER_AMI_NAME_OWNER_MAP = {
    "alinux2": {"name": "amzn2-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
    "centos7": {"name": "centos7-hvm-x86_64-*", "owners": PCLUSTER_AMI_OWNERS},
    "ubuntu1804": {"name": "ubuntu-1804-lts-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
    "ubuntu2004": {"name": "ubuntu-2004-lts-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
}

AMI_TYPE_DICT = {
    "official": OS_TO_OFFICIAL_AMI_NAME_OWNER_MAP,
    "remarkable": OS_TO_REMARKABLE_AMI_NAME_OWNER_MAP,
    "pcluster": OS_TO_PCLUSTER_AMI_NAME_OWNER_MAP,
}


def retrieve_latest_ami(region, os, ami_type="official", architecture="x86_64", additional_filters=None):
    if additional_filters is None:
        additional_filters = []
    try:
        if ami_type == "pcluster":
            ami_name = "aws-parallelcluster-{version}-{ami_name}".format(
                version=get_installed_parallelcluster_version(),
                ami_name=AMI_TYPE_DICT.get(ami_type).get(os).get("name"),
            )
        else:
            ami_name = AMI_TYPE_DICT.get(ami_type).get(os).get("name")
        logging.info("Parent image name %s" % ami_name)
        response = boto3.client("ec2", region_name=region).describe_images(
            Filters=[{"Name": "name", "Values": [ami_name]}, {"Name": "architecture", "Values": [architecture]}]
            + additional_filters,
            Owners=AMI_TYPE_DICT.get(ami_type).get(os).get("owners"),
        )
        # Sort on Creation date Desc
        amis = sorted(response.get("Images", []), key=lambda x: x["CreationDate"], reverse=True)
        return amis[0]["ImageId"]
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        raise
    except AttributeError as e:
        LOGGER.critical("Error no attribute {0} in dict: {1}".format(os, e))
        raise
    except IndexError as e:
        LOGGER.critical("Error no ami retrieved: {0}".format(e))
        raise


def retrieve_pcluster_ami_without_standard_naming(region, os, version, architecture):
    try:
        client = boto3.client("ec2", region_name=region)
        ami_name = f"ami-for-testing-pcluster-version-validation-without-standard-naming-{version}-{os}"
        official_ami_name = "aws-parallelcluster-{version}-{ami_name}".format(
            version=version, ami_name=OS_TO_PCLUSTER_AMI_NAME_OWNER_MAP.get(os).get("name")
        )
        official_amis = client.describe_images(
            Filters=[
                {"Name": "name", "Values": [official_ami_name]},
                {"Name": "architecture", "Values": [architecture]},
            ],
            Owners=["self", "amazon"],
        ).get("Images", [])
        ami_id = client.copy_image(
            Description="This AMI is a copy from an official AMI but uses a different naming. "
            "It is used to bypass the AMI's name validation of pcluster version "
            "to test the validation in Cookbook.",
            Name=ami_name,
            SourceImageId=official_amis[0]["ImageId"],
            SourceRegion=region,
        ).get("ImageId")
        _assert_ami_is_available(region, ami_id)
        return ami_id

    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        raise
    except AttributeError as e:
        LOGGER.critical("Error no attribute {0} in dict: {1}".format(os, e))
        raise
    except IndexError as e:
        LOGGER.critical("Error no ami retrieved: {0}".format(e))
        raise


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def fetch_instance_slots(region, instance_type):
    return get_instance_info(instance_type, region).get("VCpuInfo").get("DefaultVCpus")


@retry(stop_max_attempt_number=10, wait_fixed=seconds(50))
def _assert_ami_is_available(region, ami_id):
    LOGGER.info("Asserting the ami is available")
    ami_state = boto3.client("ec2", region_name=region).describe_images(ImageIds=[ami_id]).get("Images")[0].get("State")
    assert_that(ami_state).is_equal_to("available")


def get_installed_parallelcluster_version():
    """Get the version of the installed aws-parallelcluster package."""
    return pkg_resources.get_distribution("aws-parallelcluster").version


def get_sts_endpoint(region):
    """Get regionalized STS endpoint."""
    return "https://sts.{0}.{1}".format(region, "amazonaws.com.cn" if region.startswith("cn-") else "amazonaws.com")


def generate_random_string():
    """
    Generate a random prefix that is 16 characters long.

    Example: 4htvo26lchkqeho1
    """
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(16))  # nosec


def reboot_head_node(cluster, remote_command_executor=None):
    logging.info(f"Rebooting head node for cluster: {cluster.name}")
    if not remote_command_executor:
        remote_command_executor = RemoteCommandExecutor(cluster)
    command = "sudo reboot"
    result = remote_command_executor.run_remote_command(command, raise_on_error=False)
    logging.info(f"result.failed={result.failed}")
    logging.info(f"result.stdout={result.stdout}")
    wait_head_node_running(cluster)
    time.sleep(120)  # Wait time is required for the head node to complete the reboot
    logging.info(f"Rebooted head node for cluster: {cluster.name}")


def wait_head_node_running(cluster):
    logging.info(f"Waiting for head node to be running for cluster: {cluster.name}")
    boto3.client("ec2", region_name=cluster.region).get_waiter("instance_running").wait(
        Filters=[{"Name": "ip-address", "Values": [cluster.head_node_ip]}], WaiterConfig={"Delay": 60, "MaxAttempts": 5}
    )
