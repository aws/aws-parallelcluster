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
import os
import pathlib

import boto3
import pkg_resources
from assertpy import assert_that
from botocore.exceptions import ClientError
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import seconds
from utils import get_instance_info

from tests.common.schedulers_common import get_scheduler_commands

LOGGER = logging.getLogger(__name__)

SYSTEM_ANALYZER_SCRIPT = pathlib.Path(__file__).parent / "data/system-analyzer.sh"

OS_TO_OFFICIAL_AMI_NAME_OWNER_MAP = {
    "alinux2": {"name": "amzn2-ami-hvm-*.*.*.*-*-gp2", "owners": ["amazon"]},
    "centos7": {"name": "CentOS 7.*", "owners": ["125523088429"]},
    "ubuntu1804": {
        "name": "ubuntu/images/hvm-ssd/ubuntu-bionic-18.04-*-server-*",
        "owners": ["099720109477", "513442679011", "837727238323"],
    },
    "ubuntu2004": {
        "name": "ubuntu/images/hvm-ssd/ubuntu-focal-20.04-*-server-*",
        "owners": ["099720109477", "513442679011", "837727238323"],
    },
}

# Remarkable AMIs are latest deep learning base AMI and FPGA developer AMI without pcluster infrastructure
OS_TO_REMARKABLE_AMI_NAME_OWNER_MAP = {
    "alinux2": {"name": "Deep Learning Base AMI (Amazon Linux 2)*", "owners": ["amazon"]},
    "centos7": {"name": "FPGA Developer AMI*", "owners": ["679593333241"]},
    "ubuntu1804": {"name": "Deep Learning Base AMI (Ubuntu 18.04)*", "owners": ["amazon"]},
}

# Get official pcluster AMIs or get from dev account
PCLUSTER_AMI_OWNERS = ["amazon"]
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
}


def retrieve_latest_ami(region, os, ami_type="official", architecture="x86_64"):
    """
    Retrieve latest non-pcluster AMIs.

    Pcluster AMIs should be retrieved with amis_dict fixture.
    """
    try:
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
                {"Name": "is-public", "Values": ["true"]},
            ],
            Owners=OS_TO_PCLUSTER_AMI_NAME_OWNER_MAP.get(os).get("owners"),
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
def fetch_instance_slots(region, instance_type, multithreading_disabled=False):
    vcpu_info = get_instance_info(instance_type, region).get("VCpuInfo", {})
    vcpus = vcpu_info.get("DefaultVCpus")
    default_threads_per_core = vcpu_info.get("DefaultThreadsPerCore")
    if not vcpus:
        raise Exception("'DefaultVCpus' cannot be found in DescribeInstanceTypes API response.")
    if not default_threads_per_core:
        raise Exception("'DefaultThreadsPerCore' cannot be found in DescribeInstanceTypes API response.")
    return int(vcpus / default_threads_per_core) if multithreading_disabled else vcpus


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


def run_system_analyzer(cluster, scheduler, request, partition=None):
    """Run script to collect system information on head and a compute node of a cluster."""
    out_dir = request.config.getoption("output_dir")
    local_result_dir = f"{out_dir}/system_analyzer"
    compute_node_shared_dir = "/shared"
    head_node_dir = "/tmp"

    logging.info("Creating remote_command_executor and scheduler_commands")
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    logging.info(f"Retrieve head node system information for test: {request.node.name}")
    result = remote_command_executor.run_remote_script(SYSTEM_ANALYZER_SCRIPT, args=[head_node_dir])
    logging.debug(f"result.failed={result.failed}")
    logging.debug(f"result.stdout={result.stdout}")
    logging.info(
        "Copy results from remote cluster into: "
        f"{local_result_dir}/system_information_head_node_{request.node.name}.tar.gz"
    )
    os.makedirs(f"{local_result_dir}", exist_ok=True)
    remote_command_executor.get_remote_files(
        f"{head_node_dir}/system-information.tar.gz",
        f"{local_result_dir}/system_information_head_node_{request.node.name}.tar.gz",
        preserve_mode=False,
    )
    logging.info("Head node system information correctly retrieved.")

    logging.info(f"Retrieve compute node system information for test: {request.node.name}")
    result = scheduler_commands.submit_script(
        SYSTEM_ANALYZER_SCRIPT, script_args=[compute_node_shared_dir], partition=partition
    )
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
    logging.info(
        "Copy results from remote cluster into: "
        f"{local_result_dir}/system_information_compute_node_{request.node.name}.tar.gz"
    )
    remote_command_executor.get_remote_files(
        f"{compute_node_shared_dir}/system-information.tar.gz",
        f"{local_result_dir}/system_information_compute_node_{request.node.name}.tar.gz",
        preserve_mode=False,
    )
    logging.info("Compute node system information correctly retrieved.")
