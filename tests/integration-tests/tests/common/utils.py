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
import os
import pathlib
import random
import string
import time
import uuid
from importlib.metadata import version as get_package_version

import boto3
import yaml
from assertpy import assert_that
from botocore.exceptions import ClientError
from framework.framework_constants import METADATA_DEFAULT_REGION, PERFORMANCE_METADATA_TABLE
from framework.metadata_table_manager import MetadataTableManager
from packaging import version as packaging_version
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from utils import get_instance_info, get_username_for_os, run_command

from tests.common.osu_common import PRIVATE_OSES

LOGGER = logging.getLogger(__name__)

SYSTEM_ANALYZER_SCRIPT = pathlib.Path(__file__).parent / "data/system-analyzer.sh"

# Cluster node types exercised by the integration tests.
HEAD_NODE = "HeadNode"
COMPUTE_NODE = "ComputeNode"
LOGIN_NODE = "LoginNode"
NODE_TYPES = (HEAD_NODE, COMPUTE_NODE, LOGIN_NODE)

# Shared Slurm job script that builds and runs a single CUDA sample on a GPU
# compute node. Used by multiple tests to validate GPU workloads.
GPU_JOB_SCRIPT = pathlib.Path(__file__).parent / "data/gpu_job.sh"

RHEL_OWNERS = ["309956199498", "841258680906", "219670896067"]

OS_TO_OFFICIAL_AMI_NAME_OWNER_MAP = {
    "alinux2023": {"name": "al2023-ami-2023.*.*.*-kernel-6.1-*", "owners": ["amazon"]},
    # TODO: use marketplace AMI if possible
    "ubuntu2204": {
        "name": "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-*-server-*",
        "owners": ["099720109477"],
    },
    "ubuntu2404": {
        "name": "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-*-server-*",
        "owners": ["099720109477"],
    },
    # FIXME: unpin once Lustre client is available for RHEL8.9
    # FIXME: when fixed upstream, unpin the timestamp introduced because the `kernel-devel` package was missing for
    # the kernel released in 20231127 RHEL 8.8 AMI
    "rhel8": {"name": "RHEL-8.10*", "owners": RHEL_OWNERS},
    "rocky8": {
        "name": "Rocky-8-EC2-Base-8.10*",
        "owners": ["792107900819"],
        "includeDeprecated": True,  # Latest official Rocky8 AMI is deprecated:
        # https://forums.rockylinux.org/t/rocky-8-10-amis-missing-from-aws-eu-west-1-region/20558
    },  # TODO add china and govcloud accounts
    "rhel8.9": {"name": "RHEL-8.9*_HVM-*", "owners": RHEL_OWNERS},
    "rocky8.9": {"name": "Rocky-8-EC2-Base-8.9*", "owners": ["792107900819"]},  # TODO add china and govcloud accounts
    "rhel9": {"name": "RHEL-9.*_HVM*", "owners": RHEL_OWNERS},
    "rocky9": {"name": "Rocky-9-EC2-Base-9.*", "owners": ["792107900819"]},  # TODO add china and govcloud accounts
}

# Remarkable AMIs are latest deep learning base AMI and FPGA developer AMI without pcluster infrastructure
OS_TO_REMARKABLE_AMI_NAME_OWNER_MAP = {
    "alinux2023": {
        "name": {
            "x86_64": "Deep Learning Base OSS Nvidia Driver GPU AMI (Amazon Linux 2023)*",
            "arm64": "Deep Learning ARM64 Base OSS Nvidia Driver GPU AMI (Amazon Linux 2023)*",
        },
        "owners": ["amazon"],
    },
    "ubuntu2204": {
        "name": {
            "x86_64": "Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04)*",
            "arm64": "Deep Learning ARM64 Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04)*",
        },
        "owners": ["amazon"],
    },
    "ubuntu2404": {
        "name": "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-*-server-*",
        "owners": ["099720109477"],
    },
    # Simple redhat8 to be able to build in remarkable test
    "rhel8": {"name": "RHEL-8.8*_HVM-*", "owners": RHEL_OWNERS},
    "rocky8": {
        "name": "Rocky-8-EC2-Base-8.10*",
        "owners": ["792107900819"],
        "includeDeprecated": True,  # Latest official Rocky8 AMI is deprecated:
        # https://forums.rockylinux.org/t/rocky-8-10-amis-missing-from-aws-eu-west-1-region/20558
    },  # TODO add china and govcloud accounts
    "rhel8.9": {"name": "RHEL-8.9*_HVM-*", "owners": RHEL_OWNERS},
    "rocky8.9": {"name": "Rocky-8-EC2-Base-8.9*", "owners": ["792107900819"]},  # TODO add china and govcloud accounts
    "rhel9": {"name": "RHEL-9.*_HVM*", "owners": RHEL_OWNERS},
    "rocky9": {"name": "Rocky-9-EC2-Base-9.*", "owners": ["792107900819"]},  # TODO add china and govcloud accounts
}

# Get official pcluster AMIs or get from dev account
PCLUSTER_AMI_OWNERS = ["amazon", "self"]
# Pcluster AMIs are latest ParallelCluster official AMIs that align with cli version
OS_TO_PCLUSTER_AMI_NAME_OWNER_MAP = {
    "alinux2023": {"name": "amzn2023-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
    "ubuntu2204": {"name": "ubuntu-2204-lts-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
    "ubuntu2404": {"name": "ubuntu-2404-lts-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
    "rhel8": {"name": "rhel8-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
    "rocky8": {"name": "rocky8-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
    "rhel9": {"name": "rhel9-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
    "rocky9": {"name": "rocky9-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
}

FIRST_STAGE_AMI_OWNERS = ["self", "447714826191"]
OS_TO_FIRST_STAGE_AMI_NAME_MAP = {
    "alinux2023": {"name": "first-stage-aws-parallelcluster-*-amzn2023-*", "owners": FIRST_STAGE_AMI_OWNERS},
    "ubuntu2204": {"name": "first-stage-aws-parallelcluster-*-ubuntu-2204-*", "owners": FIRST_STAGE_AMI_OWNERS},
    "ubuntu2404": {"name": "first-stage-aws-parallelcluster-*-ubuntu-2404-*", "owners": FIRST_STAGE_AMI_OWNERS},
    "rhel8": {"name": "first-stage-aws-parallelcluster-*-rhel8-*", "owners": FIRST_STAGE_AMI_OWNERS},
    "rocky8": {"name": "first-stage-aws-parallelcluster-*-rocky8-*", "owners": FIRST_STAGE_AMI_OWNERS},
    "rhel9": {"name": "first-stage-aws-parallelcluster-*-rhel9-*", "owners": FIRST_STAGE_AMI_OWNERS},
    "rocky9": {"name": "first-stage-aws-parallelcluster-*-rocky9-*", "owners": FIRST_STAGE_AMI_OWNERS},
}

AMI_TYPE_DICT = {
    "official": OS_TO_OFFICIAL_AMI_NAME_OWNER_MAP,
    "remarkable": OS_TO_REMARKABLE_AMI_NAME_OWNER_MAP,
    "pcluster": OS_TO_PCLUSTER_AMI_NAME_OWNER_MAP,
    "first_stage": OS_TO_FIRST_STAGE_AMI_NAME_MAP,
}


def retrieve_latest_ami(
    region,
    os,
    ami_type="official",
    architecture="x86_64",
    additional_filters=None,
    request=None,
    allow_private_ami=False,
):
    logging.info(
        "Retrieving AMI with ami_type=%s os=%s architecture=%s allow_private_ami=%s"
        % (ami_type, os, architecture, allow_private_ami)
    )
    if additional_filters is None:
        additional_filters = []
    try:
        if ami_type == "pcluster":
            ami_name = "aws-parallelcluster-{version}-{ami_name}".format(
                version=get_installed_parallelcluster_version(),
                ami_name=_get_ami_for_os(ami_type, os, architecture).get("name"),
            )
            if (
                request
                and not request.config.getoption("pcluster_git_ref")
                and not request.config.getoption("cookbook_git_ref")
                and not request.config.getoption("node_git_ref")
                and not allow_private_ami
                and os not in PRIVATE_OSES
            ):  # If none of Git refs is provided, the test is running against released version.
                # Then retrieve public pcluster AMIs
                additional_filters.append({"Name": "is-public", "Values": ["true"]})
        else:
            ami_name = _get_ami_for_os(ami_type, os, architecture).get("name")
        describe_images_args = {
            "Filters": [{"Name": "name", "Values": [ami_name]}, {"Name": "architecture", "Values": [architecture]}]
            + additional_filters,
            "Owners": _get_ami_for_os(ami_type, os, architecture).get("owners"),
            "IncludeDeprecated": _get_ami_for_os(ami_type, os, architecture).get("includeDeprecated", False),
        }
        logging.info("Retrieving AMI with DescribeImages arguments: %s" % describe_images_args)
        paginator = boto3.client("ec2", region_name=region).get_paginator("describe_images")
        page_iterator = paginator.paginate(**describe_images_args)
        images = []
        for page in page_iterator:
            images.extend(page["Images"])
        # Sort on Creation date Desc
        image_id = sorted(images, key=lambda x: x["CreationDate"], reverse=True)[0]["ImageId"]
        logging.info("Retrieved AMI: %s" % image_id)
        return image_id
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        raise
    except AttributeError as e:
        LOGGER.critical("Error no attribute {0} in dict: {1}".format(os, e))
        raise
    except IndexError as e:
        LOGGER.critical("Error no ami retrieved: {0}".format(e))
        raise


def _get_ami_for_os(ami_type, os, architecture="x86_64"):
    ami_dict = AMI_TYPE_DICT.get(ami_type)
    if not ami_dict:
        raise Exception(f"'{ami_type}' not found in the dict 'AMI_TYPE_DICT'")
    os_ami = ami_dict.get(os)
    if not os_ami:
        raise Exception(f"'{os}' not found in the '{ami_type}' mapping referenced in the 'AMI_TYPE_DICT'")

    # Get correct AMI names as per architecture
    if isinstance(os_ami.get("name"), dict):
        name = os_ami["name"].get(architecture)
        return {"name": name, "owners": os_ami["owners"]}

    return os_ami


def retrieve_pcluster_ami_without_standard_naming(region, os, version, architecture):
    try:
        client = boto3.client("ec2", region_name=region)
        ami_name = f"ami-for-testing-pcluster-version-validation-without-standard-naming-{version}-{os}"
        official_ami_name = "aws-parallelcluster-{version}-{ami_name}".format(
            version=version, ami_name=OS_TO_PCLUSTER_AMI_NAME_OWNER_MAP.get(os).get("name")
        )
        paginator = client.get_paginator("describe_images")
        page_iterator = paginator.paginate(
            Filters=[
                {"Name": "name", "Values": [official_ami_name]},
                {"Name": "architecture", "Values": [architecture]},
            ],
            Owners=["self", "amazon"],
            IncludeDeprecated=True,
        )
        official_amis = []
        for page in page_iterator:
            official_amis.extend(page["Images"])
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
    try:
        return get_package_version("aws-parallelcluster")
    except Exception:
        logging.info("aws-parallelcluster is not installed through Python. Getting version from `pcluster version`.")
        return json.loads(run_command(["pcluster", "version"]).stdout.strip())["version"]


def get_installed_parallelcluster_base_version():
    return packaging_version.parse(get_installed_parallelcluster_version()).base_version


CLASSIC_AWS_DOMAIN = "amazonaws.com"
CHINA_AWS_DOMAIN = "amazonaws.com.cn"
US_ISO_AWS_DOMAIN = "c2s.ic.gov"
US_ISOB_AWS_DOMAIN = "sc2s.sgov.gov"


def get_aws_domain(region: str):
    """Get AWS domain for the given region."""
    if region.startswith("cn-"):
        return CHINA_AWS_DOMAIN
    elif region.startswith("us-iso-"):
        return US_ISO_AWS_DOMAIN
    elif region.startswith("us-isob-"):
        return US_ISOB_AWS_DOMAIN
    else:
        return CLASSIC_AWS_DOMAIN


def get_sts_endpoint(region):
    """Get regionalized STS endpoint."""
    return "https://sts.{0}.{1}".format(region, get_aws_domain(region))


def is_blank(value):
    """Return True if the value is None or an empty/whitespace-only string."""
    return value is None or value.strip() == ""


def generate_random_string():
    """
    Generate a random prefix that is 16 characters long.

    Example: 4htvo26lchkqeho1
    """
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(16))  # nosec


def restart_head_node(cluster):
    # stop/start head_node
    logging.info(f"Restarting head node for cluster: {cluster.name}")
    head_node_instance = cluster.get_cluster_instance_ids(node_type="HeadNode")
    ec2_client = boto3.client("ec2", region_name=cluster.region)
    ec2_client.stop_instances(InstanceIds=head_node_instance)
    ec2_client.get_waiter("instance_stopped").wait(InstanceIds=head_node_instance)
    ec2_client.start_instances(InstanceIds=head_node_instance)
    ec2_client.get_waiter("instance_status_ok").wait(InstanceIds=head_node_instance)
    time.sleep(120)  # Wait time is required for the head node to complete the reboot
    logging.info(f"Restarted head node for cluster: {cluster.name}")


def reboot_head_node(cluster, remote_command_executor=None):
    logging.info(f"Rebooting head node for cluster: {cluster.name}")
    if not remote_command_executor:
        remote_command_executor = RemoteCommandExecutor(cluster)
    command = "sudo reboot"
    result = remote_command_executor.run_remote_command(command, raise_on_error=False)
    logging.info(f"result.failed={result.failed}")
    logging.info(f"result.stdout={result.stdout}")
    wait_head_node_running(cluster)
    # Wait time is required for the head node to complete the reboot.
    # We observed that headnode in US isolated regions may take more time to reboot.
    time.sleep(300 if "us-iso" in cluster.region else 120)
    logging.info(f"Rebooted head node for cluster: {cluster.name}")


def reboot_login_node(cluster, remote_command_executor=None):
    logging.info(f"Rebooting login node for cluster: {cluster.name}")
    if not remote_command_executor:
        remote_command_executor = RemoteCommandExecutor(cluster, use_login_node=True)
    command = "sudo reboot"
    result = remote_command_executor.run_remote_command(command, raise_on_error=False)
    logging.info(f"result.failed={result.failed}")
    logging.info(f"result.stdout={result.stdout}")
    wait_login_node_running(cluster)
    wait_login_node_status_ok(cluster)
    # Wait time is required for the login node to complete the reboot.
    # We observed that loginnode in US isolated regions may take more time to reboot.
    time.sleep(240 if "us-iso" in cluster.region else 120)
    logging.info(f"Rebooted login node for cluster: {cluster.name}")


def wait_head_node_running(cluster):
    logging.info(f"Waiting for head node to be running for cluster: {cluster.name}")
    boto3.client("ec2", region_name=cluster.region).get_waiter("instance_running").wait(
        InstanceIds=cluster.get_cluster_instance_ids(node_type="HeadNode"), WaiterConfig={"Delay": 60, "MaxAttempts": 5}
    )


def wait_login_node_running(cluster):
    logging.info(f"Waiting for login node to be running for cluster: {cluster.name}")
    boto3.client("ec2", region_name=cluster.region).get_waiter("instance_running").wait(
        InstanceIds=cluster.get_cluster_instance_ids(node_type="LoginNode"),
        WaiterConfig={"Delay": 60, "MaxAttempts": 5},
    )


def wait_login_node_status_ok(cluster):
    logging.info(f"Waiting for login node's Status to be Ok for cluster: {cluster.name}")
    boto3.client("ec2", region_name=cluster.region).get_waiter("instance_status_ok").wait(
        InstanceIds=cluster.get_cluster_instance_ids(node_type="LoginNode"),
        WaiterConfig={"Delay": 60, "MaxAttempts": 5},
    )


@retry(stop_max_delay=minutes(3), wait_fixed=seconds(15))
def wait_node_reachable(cluster, node_ip):
    """Wait until the node at the given IP is reachable over SSH.

    Retried every 15 seconds for up to 3 minutes to absorb a reboot window, and
    confirms the node is healthy by reading its running kernel.
    """
    username = get_username_for_os(cluster.os)
    ssh_opts = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10"
    command = f"ssh {ssh_opts} -i {cluster.ssh_key} {username}@{node_ip} uname -r"
    kernel = run_command(command, timeout=30, shell=True).stdout.strip()
    logging.info("Node %s reachable over SSH; running kernel: %s", node_ip, kernel)


@retry(stop_max_delay=minutes(5), wait_fixed=seconds(10), retry_on_result=lambda ami: ami is None)
def retrieve_cluster_head_node_ami(cluster, region):
    """Return the AMI id the cluster uses, read from the cluster stack template.

    The AMI is read from the head node launch template (HeadNodeLaunchTemplate) in the
    cluster CloudFormation stack template, which is available as soon as the stack is
    created and avoids waiting for the head node instance to come up.
    """
    template = (
        boto3.client("cloudformation", region_name=region).get_template(StackName=cluster.cfn_name).get("TemplateBody")
    )
    if isinstance(template, str):
        template = yaml.safe_load(template)
    if not template:
        return None
    return template["Resources"]["HeadNodeLaunchTemplate"]["Properties"]["LaunchTemplateData"]["ImageId"]


def get_default_vpc_security_group(vpc_id, region):
    return (
        boto3.client("ec2", region_name=region)
        .describe_security_groups(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "group-name", "Values": ["default"]},
            ]
        )
        .get("SecurityGroups")[0]
        .get("GroupId")
    )


def get_route_tables(subnet_id, region):
    response = boto3.client("ec2", region_name=region).describe_route_tables(
        Filters=[{"Name": "association.subnet-id", "Values": [subnet_id]}]
    )
    return [table["RouteTableId"] for table in response["RouteTables"]]


def run_system_analyzer(cluster, scheduler_commands_factory, request, partition=None):
    """Run script to collect system information on head and a compute node of a cluster."""

    out_dir = request.config.getoption("output_dir")
    local_result_dir = f"{out_dir}/system_analyzer"
    compute_node_shared_dir = "/opt/parallelcluster/shared"
    head_node_dir = "/tmp"

    logging.info("Creating remote_command_executor and scheduler_commands")
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    logging.info(f"Retrieve head node system information for test: {request.node.name}")
    result = remote_command_executor.run_remote_script(SYSTEM_ANALYZER_SCRIPT, args=[head_node_dir], timeout=180)
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
    scheduler_commands.wait_job_completed(job_id, timeout=180)
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


def is_existing_remote_file(rce: RemoteCommandExecutor, file_path: str):
    """Return true if the file exists, false otherwise"""
    logging.info(f"Checking if remote file exists {file_path}")
    result = rce.run_remote_command(f"cat {file_path}", raise_on_error=False)
    return not result.failed


@retry(stop_max_attempt_number=5, wait_fixed=seconds(3))
def read_remote_file(remote_command_executor, file_path):
    """Reads the content of a remote file."""
    logging.info(f"Retrieving remote file {file_path}")
    result = remote_command_executor.run_remote_command(f"cat {file_path}")
    assert_that(result.failed).is_false()
    return result.stdout.strip()


@retry(stop_max_attempt_number=60, wait_fixed=seconds(180))
def wait_process_completion(remote_command_executor, pid):
    """Waits for a process with the given pid to terminate."""
    logging.info("Waiting for performance test to complete")
    command = f"""
    ps --pid {pid} > /dev/null
    [ "$?" -ne 0 ] && echo "COMPLETE" || echo "RUNNING"
    """
    result = remote_command_executor.run_remote_command(command)
    if result.stdout == "RUNNING":
        raise Exception("The process is still running")
    else:
        return result.stdout.strip()


def get_deployed_config_version(cluster, compute_node_ip: str = None, login_node_ip: str = None, bastion: str = None):
    """Retrieves the cluster config version deployed on a cluster node from its dna.json.

    If 'compute_node_ip' is specified, the config version is retrieved from that compute node.
    If 'login_node_ip' and 'bastion' are specified, it is retrieved from that login node via the bastion.
    Otherwise, it is retrieved from the head node.
    """
    dna_json = get_deployed_dna_json(cluster, compute_node_ip, login_node_ip, bastion)

    return dna_json["cluster"]["cluster_config_version"]


def get_deployed_dna_json(cluster, compute_node_ip: str = None, login_node_ip: str = None, bastion: str = None):
    """Retrieve the dna.json deployed on a cluster node via SSH.

    By default the dna.json is retrieved from the head node.
    If 'compute_node_ip' is specified, it will be retrieved from that compute node.
    If 'login_node_ip' is specified, it will be retrieved from that login node.

    Returns the parsed dna.json as a dict.

    Raises:
        RuntimeError: if the remote command fails (e.g. node is unreachable).
        ValueError: if the response is not valid JSON or does not contain the expected 'cluster' key.
    """
    command = "sudo cat /etc/chef/dna.json"
    rce = RemoteCommandExecutor(cluster, compute_node_ip=compute_node_ip, login_node_ip=login_node_ip, bastion=bastion)

    try:
        result = rce.run_remote_command(command).stdout
        dna_json = json.loads(result)
    except RemoteCommandExecutionError as e:
        raise RuntimeError(f"Cannot retrieve dna.json from cluster node ({rce.target}): {e}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Returned value should be a dna.json, but it's not a valid JSON: {e}")

    if "cluster" not in dna_json:
        raise ValueError("Returned value should be a dna.json, but it does not contain the expected 'cluster' key")

    return dna_json


@retry(wait_fixed=seconds(3), stop_max_delay=seconds(15))
def get_ddb_item(region_name: str, table_name: str, item_key: dict):
    """Retrieves the item from the specified DynamoDB table and region by key.
    It returns None if the item does not exist.
    """
    table = boto3.resource("dynamodb", region_name=region_name).Table(table_name)
    return table.get_item(Key=item_key).get("Item")


def get_config_version_from_ddb(region, cluster_name, instance_id):
    """Get the current cluster config version from DynamoDB."""
    dynamodb = boto3.client("dynamodb", region_name=region)
    table_name = f"parallelcluster-{cluster_name}"
    ddb_key = f"CLUSTER_CONFIG.{instance_id}"

    response = dynamodb.get_item(TableName=table_name, Key={"Id": {"S": ddb_key}})

    if "Item" in response:
        data = response["Item"].get("Data", {}).get("M", {})
        return data.get("cluster_config_version", {}).get("S", "")

    raise ValueError(f"No DynamoDB record found for instance {instance_id}")


def get_compute_ip_to_num_files(remote_command_executor, slurm_commands):
    """Gets a mapping of compute node instance ip to its current number of open files."""
    logging.info("Checking the number of file descriptors...")

    # Submit job to the test nodes
    compute_node_names = slurm_commands.get_compute_nodes(all_nodes=True)
    for name in compute_node_names:
        slurm_commands.submit_command_and_assert_job_accepted(
            submit_command_args={"command": "srun sleep 1", "host": name}
        )
    # Wait for all jobs to be completed
    slurm_commands.wait_job_queue_empty()

    # Get the number of open files on all the nodes
    instance_ip_to_num_files = {}
    for node_name in compute_node_names:
        compute_node_instance_ip = slurm_commands.get_node_addr(node_name)
        install_cmd = (
            f"ssh -q {compute_node_instance_ip} 'sudo yum install -y lsof "
            "|| sudo apt-get update && sudo apt-get install -y lsof'"
        )
        remote_command_executor.run_remote_command(install_cmd, raise_on_error=False)
        lsof_cmd = f"ssh -q {compute_node_instance_ip} 'sudo lsof -p $(pgrep computemgtd) | wc -l'"
        num_files = remote_command_executor.run_remote_command(lsof_cmd).stdout
        instance_ip_to_num_files[compute_node_instance_ip] = num_files

    logging.info(f"Mapping from instance ip to number of open files in computemgtd: {instance_ip_to_num_files}")
    return instance_ip_to_num_files


def assert_no_file_handler_leak(init_compute_ip_to_num_files, remote_command_executor, slurm_commands):
    """Asserts that the current number of open files for each compute node is the same as the given map"""
    current_compute_ip_to_num_files = get_compute_ip_to_num_files(remote_command_executor, slurm_commands)
    logging.info(
        f"Asserting that the number of open files in computemgtd hasn't grown from "
        f"{init_compute_ip_to_num_files} to {current_compute_ip_to_num_files}."
    )
    for compute_ip in current_compute_ip_to_num_files:
        if compute_ip in init_compute_ip_to_num_files:
            assert_that(current_compute_ip_to_num_files[compute_ip]).is_equal_to(
                init_compute_ip_to_num_files[compute_ip]
            )


def write_file(dirname, filename, content):
    os.makedirs(dirname, exist_ok=True)
    filepath = f"{dirname}/{filename}"
    with open(filepath, "w") as f:
        f.write(content)
    logging.info(f"File written: {filepath}")
    return filepath


def terminate_nodes_manually(instance_ids, region):
    ec2_client = boto3.client("ec2", region_name=region)
    for instance_id in instance_ids:
        instance_states = ec2_client.terminate_instances(InstanceIds=[instance_id]).get("TerminatingInstances")[0]
        assert_that(instance_states.get("InstanceId")).is_equal_to(instance_id)
        assert_that(instance_states.get("CurrentState").get("Name")).is_in("shutting-down", "terminated")
    logging.info("Terminated nodes: {}".format(instance_ids))


def get_capacity_reservation_id(request, instance_type, region, count, os):
    os_platform = "Linux/UNIX"
    if "rhel" in os.lower():
        os_platform = "Red Hat Enterprise Linux"

    # List to store matching reservation IDs
    reservations_ids = []
    ec2_client = boto3.client("ec2", region_name=region)
    if request.config.getoption("capacity_reservation_id"):
        capacity_reservation = ec2_client.describe_capacity_reservations(
            CapacityReservationIds=[request.config.getoption("capacity_reservation_id")]
        )
        if capacity_reservation:
            reservations_ids.append(
                {
                    "CapacityReservationId": capacity_reservation.get("CapacityReservations", [])[0][
                        "CapacityReservationId"
                    ],
                    "TotalInstanceCount": capacity_reservation.get("CapacityReservations", [])[0]["TotalInstanceCount"],
                    "AvailableInstanceCount": capacity_reservation.get("CapacityReservations", [])[0][
                        "AvailableInstanceCount"
                    ],
                }
            )
    else:
        paginator = ec2_client.get_paginator("describe_capacity_reservations")
        # Paginate through the results
        for page in paginator.paginate():
            for reservation in page.get("CapacityReservations", []):
                if (
                    instance_type == reservation.get("InstanceType")
                    and os_platform == reservation.get("InstancePlatform")
                    and reservation.get("AvailableInstanceCount") >= count
                    and reservation.get("State") == "active"
                    and reservation["CapacityReservationId"] != "cr-08be2f796cdaf5015"
                    # Skip this Gb200 Capacity Reservation which fails NCCL benchmarks
                ):
                    reservations_ids.append(
                        {
                            "CapacityReservationId": reservation["CapacityReservationId"],
                            "TotalInstanceCount": reservation["TotalInstanceCount"],
                            "AvailableInstanceCount": reservation["AvailableInstanceCount"],
                        }
                    )
    return reservations_ids


def push_result_to_dynamodb(name, result, instance, os, mpi_variation=None, num_instances=None):
    reporting_region = METADATA_DEFAULT_REGION
    logging.info(f"Metadata reporting region {reporting_region}")
    # Create the metadata table in case it doesn't exist
    MetadataTableManager(reporting_region, PERFORMANCE_METADATA_TABLE).create_metadata_table()
    try:
        # Create DynamoDB resource
        dynamodb = boto3.resource("dynamodb", region_name=reporting_region)
        table = dynamodb.Table(PERFORMANCE_METADATA_TABLE)

        # Prepare item to be inserted
        item = {
            "id": str(uuid.uuid4().hex),
            "name": name,
            "instance": instance,
            "os": os,
            "timestamp": int(time.time()),
            "result": str(result),
            "pcluster_version": f"v{get_installed_parallelcluster_version()}",
            "mpi_variation": str(mpi_variation),
            "num_instances": num_instances,
        }

        # Put item in the table
        table.put_item(Item=item)
        logging.info(f"Successfully pushed result to DynamoDB with id: {item['id']}")

    except Exception as e:
        logging.error(f"Failed to push result to DynamoDB: {str(e)}")
        raise


@retry(stop_max_attempt_number=3, wait_fixed=seconds(10))
def _download_and_upload_to_s3(url, bucket_name, s3_key, s3_client):
    """Download a file from a URL and upload it to S3, with retries for transient network failures."""
    import tempfile
    import urllib.request

    with tempfile.NamedTemporaryFile(suffix=".tgz") as tmp:
        urllib.request.urlretrieve(url, tmp.name)
        s3_client.upload_file(tmp.name, bucket_name, s3_key)


def upload_github_artifacts_to_s3(bucket_name, region, request):
    """Upload GitHub repository tarballs to S3 for use in isolated network environments.

    Downloads packages from GitHub URLs specified in test config options and uploads
    them to S3 so build instances can access them via S3 VPC endpoints instead of
    requiring direct internet access to GitHub.

    Returns a dict with S3 URLs keyed by package type.
    """
    s3_client = boto3.client("s3", region_name=region)
    result = {}

    option_to_s3_key = {
        "createami_custom_chef_cookbook": ("chef_cookbook", "packages/aws-parallelcluster-cookbook.tgz"),
        "createami_custom_node_package": ("node_package", "packages/aws-parallelcluster-node.tgz"),
    }

    for option_name, (result_key, s3_key) in option_to_s3_key.items():
        url = request.config.getoption(option_name, default=None)
        if url:
            logging.info("Downloading %s from %s", option_name, url)
            _download_and_upload_to_s3(url, bucket_name, s3_key, s3_client)
            result[result_key] = f"s3://{bucket_name}/{s3_key}"
            logging.info("Uploaded %s to s3://%s/%s", option_name, bucket_name, s3_key)
        else:
            result[result_key] = ""

    return result


def wait_for_no_active_export_tasks(region):
    """Wait until there are no active CloudWatch Logs export tasks in the region.

    Each account can only have one active (RUNNING or PENDING) export task per region at a time.
    This function uses the statusCode filter to query only active tasks server-side,
    preventing conflicts with subsequent export calls and avoiding pagination through
    years of completed historical tasks.
    See: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_CreateExportTask.html
    """
    logging.info("Starting the check for active export tasks in region %s", region)
    active_statuses = ("RUNNING", "PENDING")
    logs_client = boto3.client("logs", region_name=region)
    max_wait = 300  # 5 minutes
    poll_interval = random.randint(10, 20)
    elapsed = 0
    while elapsed < max_wait:
        active_tasks = []
        for status_code in active_statuses:
            response = logs_client.describe_export_tasks(statusCode=status_code)
            active_tasks.extend(response.get("exportTasks", []))
        if not active_tasks:
            logging.info("No active export tasks in region %s", region)
            return
        logging.info(
            "Waiting for %d active export task(s) to complete in region %s (%ds elapsed): %s",
            len(active_tasks),
            region,
            elapsed,
            [
                {
                    "taskId": t.get("taskId"),
                    "status": t.get("status", {}).get("code"),
                    "logGroup": t.get("logGroupName"),
                }
                for t in active_tasks
            ],
        )
        time.sleep(poll_interval)
        elapsed += poll_interval
    logging.warning("Timed out waiting for export tasks to complete after %ds", max_wait)
