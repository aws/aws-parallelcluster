# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import logging

import boto3
import pytest
import utils
from assertpy import assert_that
from cfn_stacks_factory import CfnStack
from constants import OSU_BENCHMARK_VERSION
from fabric import Connection
from remote_command_executor import RemoteCommandExecutor
from troposphere import Template
from troposphere.ec2 import EIP
from utils import generate_stack_name, get_compute_nodes_instance_ids, get_username_for_os, render_jinja_template

from tests.common.assertions import (
    assert_lambda_vpc_settings_are_correct,
    assert_no_errors_in_logs,
    assert_no_msg_in_logs,
    wait_for_num_instances_in_cluster,
)
from tests.common.osu_common import compile_osu
from tests.common.schedulers_common import SlurmCommands
from tests.common.storage.constants import StorageType
from tests.common.utils import get_default_vpc_security_group
from tests.storage.storage_common import (
    assert_fsx_lustre_correctly_mounted,
    get_efs_ids,
    get_fsx_ids,
    test_efs_correctly_mounted,
    verify_directory_correctly_shared,
)


@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_cluster_in_private_subnet(
    region, pcluster_config_reader, clusters_factory, vpc_stack, scheduler_commands_factory
):
    # This test just creates a cluster in the private subnet and just checks that no failures occur
    storage_type = StorageType.STORAGE_EFS if "us-iso" in region else StorageType.STORAGE_FSX
    mount_dir = "/private_storage_mount"
    cluster_config = pcluster_config_reader(storage_type=storage_type.value, mount_dir=mount_dir)
    cluster = clusters_factory(cluster_config)
    assert_that(cluster).is_not_none()

    bastion = vpc_stack.cfn_outputs["BastionUser"] + "@" + vpc_stack.cfn_outputs["BastionIP"]
    assert_that(len(get_compute_nodes_instance_ids(cluster.cfn_name, region))).is_equal_to(1)
    remote_command_executor = RemoteCommandExecutor(cluster, bastion=bastion)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    _test_shared_storage_in_private_subnet(
        cluster, region, storage_type, mount_dir, remote_command_executor, scheduler_commands
    )
    lambda_vpc_config = cluster.config["DeploymentSettings"]["LambdaFunctionsVpcConfig"]
    assert_lambda_vpc_settings_are_correct(
        cluster.cfn_name, region, lambda_vpc_config["SecurityGroupIds"], lambda_vpc_config["SubnetIds"]
    )


@pytest.fixture(scope="class")
def existing_eip(region, request, cfn_stacks_factory):
    template = Template()
    template.set_version("2010-09-09")
    template.set_description("EIP stack for testing existing EIP")
    template.add_resource(EIP("ElasticIP", Domain="vpc"))
    stack = CfnStack(
        name=generate_stack_name("integ-tests-eip", request.config.getoption("stackname_suffix")),
        region=region,
        template=template.to_json(),
    )
    cfn_stacks_factory.create_stack(stack)

    yield stack.cfn_resources["ElasticIP"]

    if not request.config.getoption("no_delete"):
        cfn_stacks_factory.delete_stack(stack.name, region)


@pytest.mark.usefixtures("os", "scheduler", "instance", "region")
def test_existing_eip(existing_eip, pcluster_config_reader, clusters_factory):
    cluster_config = pcluster_config_reader(elastic_ip=existing_eip)
    cluster = clusters_factory(cluster_config)
    assert_that(cluster).is_not_none()
    username = get_username_for_os(cluster.os)
    connection = Connection(
        host=existing_eip,
        user=username,
        forward_agent=False,
        connect_kwargs={"key_filename": [cluster.ssh_key]},
    )
    # Run arbitrary command to test if we can use the elastic ip to log into the instance.
    connection.run("cat /var/log/cfn-init.log", timeout=60)


def _test_shared_storage_in_private_subnet(
    cluster, region, storage_type, mount_dir, remote_command_executor, scheduler_commands
):
    """Test FSx can be mounted in private subnet."""
    if storage_type == StorageType.STORAGE_EFS:
        fs_id = get_efs_ids(cluster, region)[0]
        test_efs_correctly_mounted(remote_command_executor, mount_dir, region, fs_id)
    elif storage_type == StorageType.STORAGE_FSX:
        fs_id = get_fsx_ids(cluster, region)[0]
        assert_fsx_lustre_correctly_mounted(remote_command_executor, mount_dir, region, fs_id)
    else:
        raise Exception(f"The storage type '{storage_type}' is not supported in this test.")
    verify_directory_correctly_shared(
        remote_command_executor, mount_dir, scheduler_commands, partitions=scheduler_commands.get_partitions()
    )


@pytest.mark.usefixtures("instance")
def test_cluster_in_no_internet_subnet(
    region,
    scheduler,
    pcluster_config_reader,
    vpc_stack_with_endpoints,
    s3_bucket_factory,
    clusters_factory,
    test_datadir,
    architecture,
    os,
    mpi_variants,
):
    """
    This test creates a cluster in a subnet with no internet, run simple integration test to check prolog and epilog
    script failure, then run osu latency and checks that no failures occur.
    """
    bucket_name = s3_bucket_factory()
    _upload_pre_install_script(bucket_name, test_datadir)

    vpc_default_security_group_id = get_default_vpc_security_group(
        vpc_stack_with_endpoints.cfn_outputs["VpcId"], region
    )
    cluster_config = pcluster_config_reader(
        default_vpc_security_group_id=vpc_stack_with_endpoints.cfn_outputs["DefaultVpcSecurityGroupId"],
        no_internet_subnet_id=vpc_stack_with_endpoints.cfn_outputs["PrivateNoInternetSubnetId"],
        vpc_default_security_group_id=vpc_default_security_group_id,
        bucket_name=bucket_name,
        architecture=architecture,
    )
    cluster = clusters_factory(cluster_config)

    logging.info("Checking cluster has one static node")
    assert_that(len(get_compute_nodes_instance_ids(cluster.cfn_name, region))).is_equal_to(1)

    bastion = (
        vpc_stack_with_endpoints.cfn_outputs["BastionUser"] + "@" + vpc_stack_with_endpoints.cfn_outputs["BastionIP"]
    )
    remote_command_executor = RemoteCommandExecutor(cluster, bastion=bastion)
    slurm_commands = SlurmCommands(remote_command_executor)

    _check_no_internet_access(remote_command_executor)
    _check_hostname(remote_command_executor)
    _run_prolog_epilog_jobs(remote_command_executor, slurm_commands)
    _run_mpi_jobs(mpi_variants, remote_command_executor, test_datadir, slurm_commands, cluster, region)
    utils.check_pcluster_list_cluster_log_streams(cluster, os)
    assert_no_errors_in_logs(remote_command_executor, scheduler)
    logging.info("Checking compute node is scaled down after scaledown idle time")
    wait_for_num_instances_in_cluster(cluster.cfn_name, region, 1)

    lambda_vpc_config = cluster.config["DeploymentSettings"]["LambdaFunctionsVpcConfig"]
    assert_lambda_vpc_settings_are_correct(
        cluster.cfn_name, region, lambda_vpc_config["SecurityGroupIds"], lambda_vpc_config["SubnetIds"]
    )


def _upload_pre_install_script(bucket_name, test_datadir):
    bucket = boto3.resource("s3").Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "pre_install.sh"), "scripts/pre_install.sh")


def _check_no_internet_access(remote_command_executor):
    logging.info("Checking cluster has no Internet access by trying to access google.com")
    internet_result = remote_command_executor.run_remote_command(
        "curl --connect-timeout 10 -I https://google.com", raise_on_error=False
    )
    assert_that(internet_result.failed).is_true()


def _check_hostname(remote_command_executor):
    logging.info("Checking compute node's hostname is ip-x-x-x-x")
    hostname = remote_command_executor.run_remote_command("srun hostname").stdout
    assert_that(hostname).matches(r"^ip-\d+-\d+-\d+-\d+$")


def _run_prolog_epilog_jobs(remote_command_executor, slurm_commands):
    logging.info("Running simple test to verify prolog and epilog")
    logging.info("Test one job on 2 nodes")
    job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "uptime", "nodes": 2}
    )
    slurm_commands.wait_job_completed(job_id)
    assert_no_msg_in_logs(remote_command_executor, ["/var/log/slurmctld.log"], ["launch failure"])
    logging.info("Test 2 jobs simultaneously run on 2 nodes")
    # 720 to have enough to run another job even node creation
    job_id = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "sleep 720", "nodes": 2}
    )
    slurm_commands.wait_job_running(job_id)
    # --no-requeue to make the job fail in case of prolog or epilog error
    job_id_1 = slurm_commands.submit_command_and_assert_job_accepted(
        submit_command_args={"command": "uptime", "nodes": 2, "other_options": "--no-requeue"}
    )
    slurm_commands.wait_job_completed(job_id_1)
    # Check if the prolog and epilog run correctly
    slurm_commands.assert_job_succeeded(job_id_1)
    assert_no_msg_in_logs(remote_command_executor, ["/var/log/slurmctld.log"], ["launch failure"])
    slurm_commands.cancel_job(job_id)


def _run_mpi_jobs(mpi_variants, remote_command_executor, test_datadir, slurm_commands, cluster, region):
    for mpi_variant in mpi_variants:
        logging.info(f"Running OSU benchmark {OSU_BENCHMARK_VERSION} for {mpi_variant}")
        compile_osu(mpi_variant, remote_command_executor)
        submission_script = render_jinja_template(
            template_file_path=test_datadir / f"osu_pt2pt_submit_{mpi_variant}.sh",
            osu_benchmark_version=OSU_BENCHMARK_VERSION,
        )
        result = slurm_commands.submit_script(str(submission_script))
        job_id = slurm_commands.assert_job_submitted(result.stdout)
        slurm_commands.wait_job_completed(job_id, timeout=15)
        slurm_commands.assert_job_succeeded(job_id)
    logging.info("Checking cluster has two nodes after running MPI jobs")  # 1 static node + 1 dynamic node
    assert_that(len(get_compute_nodes_instance_ids(cluster.cfn_name, region))).is_equal_to(2)
