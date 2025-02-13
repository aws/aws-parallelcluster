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

import boto3
import pkg_resources
from assertpy import assert_that
from botocore.exceptions import ClientError
from remote_command_executor import RemoteCommandExecutionError, RemoteCommandExecutor
from retrying import retry
from time_utils import seconds
from utils import get_instance_info, run_command

from tests.common.osu_common import PRIVATE_OSES

LOGGER = logging.getLogger(__name__)

SYSTEM_ANALYZER_SCRIPT = pathlib.Path(__file__).parent / "data/system-analyzer.sh"

RHEL_OWNERS = ["309956199498", "841258680906", "219670896067"]

OS_TO_OFFICIAL_AMI_NAME_OWNER_MAP = {
    "alinux2": {"name": "amzn2-ami-kernel-5.10-hvm-*.*.*.*-*-gp2", "owners": ["amazon"]},
    "alinux2023": {"name": "al2023-ami-2023.*.*.*-kernel-6.1-*", "owners": ["amazon"]},
    # TODO: use marketplace AMI if possible
    "ubuntu2004": {
        "name": "ubuntu/images/hvm-ssd/ubuntu-focal-20.04-*-server-*",
        "owners": ["099720109477"],
    },
    "ubuntu2204": {
        "name": "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-*-server-*",
        "owners": ["099720109477"],
    },
    # FIXME: unpin once Lustre client is available for RHEL8.9
    # FIXME: when fixed upstream, unpin the timestamp introduced because the `kernel-devel` package was missing for
    # the kernel released in 20231127 RHEL 8.8 AMI
    "rhel8": {"name": "RHEL-8.8*_HVM-202309*", "owners": RHEL_OWNERS},
    "rocky8": {"name": "Rocky-8-EC2-Base-8.8*", "owners": ["792107900819"]},  # TODO add china and govcloud accounts
    "rhel8.9": {"name": "RHEL-8.9*_HVM-*", "owners": RHEL_OWNERS},
    "rocky8.9": {"name": "Rocky-8-EC2-Base-8.9*", "owners": ["792107900819"]},  # TODO add china and govcloud accounts
    "rhel9": {"name": "RHEL-9.*_HVM*", "owners": RHEL_OWNERS},
    "rocky9": {"name": "Rocky-9-EC2-Base-9.*", "owners": ["792107900819"]},  # TODO add china and govcloud accounts
}

# Remarkable AMIs are latest deep learning base AMI and FPGA developer AMI without pcluster infrastructure
OS_TO_REMARKABLE_AMI_NAME_OWNER_MAP = {
    "alinux2": {"name": "Deep Learning Base AMI (Amazon Linux 2)*", "owners": ["amazon"]},
    "ubuntu2004": {"name": "Deep Learning Base GPU AMI (Ubuntu 20.04)*", "owners": ["amazon"]},
    # Simple redhat8 to be able to build in remarkable test
    # FIXME: when fixed upstream, unpin the timestamp introduced because the `kernel-devel` package was missing for
    # the kernel released in 20231127 RHEL 8.8 AMI
    "rhel8": {"name": "RHEL-8.8*_HVM-202309*", "owners": RHEL_OWNERS},
    "rocky8": {"name": "Rocky-8-EC2-Base-8.8*", "owners": ["792107900819"]},  # TODO add china and govcloud accounts
    "rhel8.9": {"name": "RHEL-8.9*_HVM-*", "owners": RHEL_OWNERS},
    "rocky8.9": {"name": "Rocky-8-EC2-Base-8.9*", "owners": ["792107900819"]},  # TODO add china and govcloud accounts
    "rhel9": {"name": "RHEL-9.*_HVM*", "owners": RHEL_OWNERS},
    "rocky9": {"name": "Rocky-9-EC2-Base-9.*", "owners": ["792107900819"]},  # TODO add china and govcloud accounts
}

OS_TO_KERNEL4_AMI_NAME_OWNER_MAP = {
    "alinux2": {"name": "amzn2-ami-hvm-*.*.*.*-*-gp2", "owners": ["amazon"]},
}

# Get official pcluster AMIs or get from dev account
PCLUSTER_AMI_OWNERS = ["amazon", "self"]
# Pcluster AMIs are latest ParallelCluster official AMIs that align with cli version
OS_TO_PCLUSTER_AMI_NAME_OWNER_MAP = {
    "alinux2": {"name": "amzn2-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
    "alinux2023": {"name": "amzn2023-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
    "ubuntu2004": {"name": "ubuntu-2004-lts-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
    "ubuntu2204": {"name": "ubuntu-2204-lts-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
    "rhel8": {"name": "rhel8-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
    "rocky8": {"name": "rocky8-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
    "rhel9": {"name": "rhel9-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
    "rocky9": {"name": "rocky9-hvm-*-*", "owners": PCLUSTER_AMI_OWNERS},
}

FIRST_STAGE_AMI_OWNERS = ["self", "447714826191"]
OS_TO_FIRST_STAGE_AMI_NAME_MAP = {
    "alinux2": {"name": "first-stage-aws-parallelcluster-*-amzn2-*", "owners": FIRST_STAGE_AMI_OWNERS},
    "alinux2023": {"name": "first-stage-aws-parallelcluster-*-amzn2023-*", "owners": FIRST_STAGE_AMI_OWNERS},
    "ubuntu2004": {"name": "first-stage-aws-parallelcluster-*-ubuntu-2004-*", "owners": FIRST_STAGE_AMI_OWNERS},
    "ubuntu2204": {"name": "first-stage-aws-parallelcluster-*-ubuntu-2204-*", "owners": FIRST_STAGE_AMI_OWNERS},
    "rhel8": {"name": "first-stage-aws-parallelcluster-*-rhel8-*", "owners": FIRST_STAGE_AMI_OWNERS},
    "rocky8": {"name": "first-stage-aws-parallelcluster-*-rocky8-*", "owners": FIRST_STAGE_AMI_OWNERS},
    "rhel9": {"name": "first-stage-aws-parallelcluster-*-rhel9-*", "owners": FIRST_STAGE_AMI_OWNERS},
    "rocky9": {"name": "first-stage-aws-parallelcluster-*-rocky9-*", "owners": FIRST_STAGE_AMI_OWNERS},
}

AMI_TYPE_DICT = {
    "official": OS_TO_OFFICIAL_AMI_NAME_OWNER_MAP,
    "remarkable": OS_TO_REMARKABLE_AMI_NAME_OWNER_MAP,
    "pcluster": OS_TO_PCLUSTER_AMI_NAME_OWNER_MAP,
    "kernel4": OS_TO_KERNEL4_AMI_NAME_OWNER_MAP,
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
    if additional_filters is None:
        additional_filters = []
    try:
        if ami_type == "pcluster":
            ami_name = "aws-parallelcluster-{version}-{ami_name}".format(
                version=get_installed_parallelcluster_version(),
                ami_name=_get_ami_for_os(ami_type, os).get("name"),
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
            ami_name = _get_ami_for_os(ami_type, os).get("name")
        logging.info("Parent image name %s" % ami_name)
        paginator = boto3.client("ec2", region_name=region).get_paginator("describe_images")
        page_iterator = paginator.paginate(
            Filters=[{"Name": "name", "Values": [ami_name]}, {"Name": "architecture", "Values": [architecture]}]
            + additional_filters,
            Owners=_get_ami_for_os(ami_type, os).get("owners"),
            IncludeDeprecated=_get_ami_for_os(ami_type, os).get("includeDeprecated", False),
        )
        images = []
        for page in page_iterator:
            images.extend(page["Images"])
        # Sort on Creation date Desc
        return sorted(images, key=lambda x: x["CreationDate"], reverse=True)[0]["ImageId"]
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        raise
    except AttributeError as e:
        LOGGER.critical("Error no attribute {0} in dict: {1}".format(os, e))
        raise
    except IndexError as e:
        LOGGER.critical("Error no ami retrieved: {0}".format(e))
        raise


def _get_ami_for_os(ami_type, os):
    ami_dict = AMI_TYPE_DICT.get(ami_type)
    if not ami_dict:
        raise Exception(f"'{ami_type}' not found in the dict 'AMI_TYPE_DICT'")
    os_ami = ami_dict.get(os)
    if not os_ami:
        raise Exception(f"'{os}' not found in the '{ami_type}' mapping referenced in the 'AMI_TYPE_DICT'")
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
        return pkg_resources.get_distribution("aws-parallelcluster").version
    except Exception:
        logging.info("aws-parallelcluster is not installed through Python. Getting version from `pcluster version`.")
        return json.loads(run_command(["pcluster", "version"]).stdout.strip())["version"]


def get_installed_parallelcluster_base_version():
    return pkg_resources.packaging.version.parse(get_installed_parallelcluster_version()).base_version


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


def get_deployed_config_version(cluster, compute_node_ip: str = None):
    """Retrieves the cluster config version deployed on the cluster node from its dna.json
    If 'compute_node_ip' is specified, the config version will be retrieved from the compute node;
    otherwise, it will be retrieved from the head node.
    """
    dna_json = get_deployed_dna_json(cluster, compute_node_ip)

    return dna_json["cluster"]["cluster_config_version"]


def get_deployed_dna_json(cluster, compute_node_ip: str = None):
    """Retrieves the dna.json from the cluster node
    If 'compute_node_ip' is specified, it will be retrieved from the compute node;
    otherwise, it will be retrieved from the head node.
    """
    command = "sudo cat /etc/chef/dna.json"
    rce = (
        RemoteCommandExecutor(cluster, compute_node_ip=compute_node_ip)
        if compute_node_ip
        else RemoteCommandExecutor(cluster)
    )

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
