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
import time
from enum import Enum
from typing import NamedTuple

import boto3
import pytest
import utils
from assertpy import assert_that
from cfn_stacks_factory import CfnStack
from constants import OSU_BENCHMARK_VERSION
from fabric import Connection
from remote_command_executor import RemoteCommandExecutor
from troposphere import GetAtt, Output, Ref, Template, ec2
from troposphere.ec2 import EIP, VPCEndpoint
from utils import generate_stack_name, get_compute_nodes_instance_ids, get_username_for_os, render_jinja_template

from tests.common.assertions import assert_no_errors_in_logs, assert_no_msg_in_logs, wait_for_num_instances_in_cluster
from tests.common.osu_common import compile_osu
from tests.common.schedulers_common import SlurmCommands
from tests.common.utils import get_default_vpc_security_group, get_route_tables, retrieve_latest_ami
from tests.storage.test_fsx_lustre import assert_fsx_correctly_shared, assert_fsx_lustre_correctly_mounted, get_fsx_ids


@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_cluster_in_private_subnet(
    region, pcluster_config_reader, clusters_factory, bastion_instance, scheduler_commands_factory
):
    # This test just creates a cluster in the private subnet and just checks that no failures occur
    fsx_mount_dir = "/fsx_mount"
    cluster_config = pcluster_config_reader(fsx_mount_dir=fsx_mount_dir)
    cluster = clusters_factory(cluster_config)
    assert_that(cluster).is_not_none()

    assert_that(len(get_compute_nodes_instance_ids(cluster.cfn_name, region))).is_equal_to(1)
    remote_command_executor = RemoteCommandExecutor(cluster, bastion=bastion_instance)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    _test_fsx_in_private_subnet(
        cluster, region, fsx_mount_dir, bastion_instance, remote_command_executor, scheduler_commands
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


def _test_fsx_in_private_subnet(
    cluster, region, fsx_mount_dir, bastion_instance, remote_command_executor, scheduler_commands
):
    """Test FSx can be mounted in private subnet."""
    logging.info("Sleeping for 60 sec to wait for bastion ssh to become ready.")
    time.sleep(60)
    logging.info(f"Bastion: {bastion_instance}")
    fsx_fs_id = get_fsx_ids(cluster, region)[0]
    assert_fsx_lustre_correctly_mounted(remote_command_executor, fsx_mount_dir, region, fsx_fs_id)
    assert_fsx_correctly_shared(scheduler_commands, remote_command_executor, fsx_mount_dir)


@pytest.mark.usefixtures("enable_vpc_endpoints")
@pytest.mark.usefixtures("instance")
def test_cluster_in_no_internet_subnet(
    region,
    scheduler,
    pcluster_config_reader,
    vpc_stack,
    s3_bucket_factory,
    clusters_factory,
    test_datadir,
    architecture,
    os,
    mpi_variants,
    bastion_instance,
):
    """
    This test creates a cluster in a subnet with no internet, run simple integration test to check prolog and epilog
    script failure, then run osu latency and checks that no failures occur.
    """
    bucket_name = s3_bucket_factory()
    _upload_pre_install_script(bucket_name, test_datadir)

    vpc_default_security_group_id = get_default_vpc_security_group(vpc_stack.cfn_outputs["VpcId"], region)
    cluster_config = pcluster_config_reader(
        vpc_default_security_group_id=vpc_default_security_group_id, bucket_name=bucket_name, architecture=architecture
    )
    cluster = clusters_factory(cluster_config)

    logging.info("Checking cluster has one static node")
    assert_that(len(get_compute_nodes_instance_ids(cluster.cfn_name, region))).is_equal_to(1)

    remote_command_executor = RemoteCommandExecutor(cluster, bastion=bastion_instance)
    slurm_commands = SlurmCommands(remote_command_executor)

    _check_no_internet_access(remote_command_executor)
    _check_hostname(remote_command_executor)
    _run_prolog_epilog_jobs(remote_command_executor, slurm_commands)
    _run_mpi_jobs(mpi_variants, remote_command_executor, test_datadir, slurm_commands, cluster, region)
    expected_log_streams = {
        "HeadNode": {"cfn-init", "cloud-init", "clustermgtd", "chef-client", "slurmctld", "supervisord"},
        "Compute": {
            "syslog" if os.startswith("ubuntu") else "system-messages",
            "computemgtd",
            "supervisord",
            "slurm_prolog_epilog",
        },
    }
    utils.check_pcluster_list_cluster_log_streams(cluster, os, expected_log_streams)
    assert_no_errors_in_logs(remote_command_executor, scheduler)
    logging.info("Checking compute node is scaled down after scaledown idle time")
    wait_for_num_instances_in_cluster(cluster.cfn_name, region, 1)


def _upload_pre_install_script(bucket_name, test_datadir):
    bucket = boto3.resource("s3").Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "pre_install.sh"), "scripts/pre_install.sh")


def _check_no_internet_access(remote_command_executor):
    logging.info("Checking cluster has no Internet access by trying to access google.com")
    internet_result = remote_command_executor.run_remote_command("curl -I https://google.com", raise_on_error=False)
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


class VPCEndpointConfig(NamedTuple):
    """Configuration for a VPC Endpoint."""

    class EndpointType(Enum):
        """Type of VPC Endpoint."""

        GATEWAY = "Gateway"
        INTERFACE = "Interface"

        def __str__(self):
            return self.value

    name: str = None
    service_name: str = None
    type: EndpointType = EndpointType.INTERFACE
    enable_private_dns: bool = True


@pytest.fixture(scope="class")
def enable_vpc_endpoints(vpc_stack, region, cfn_stacks_factory, request):
    prefix = "cn." if region.startswith("cn-") else ""
    # Note that the endpoints service name in China is irregular.
    vpc_endpoints = [
        VPCEndpointConfig(
            name="LogsEndpoint",
            service_name=f"com.amazonaws.{region}.logs",
            type=VPCEndpointConfig.EndpointType.INTERFACE,
            enable_private_dns=True,
        ),
        VPCEndpointConfig(
            name="CFNEndpoint",
            service_name=prefix + f"com.amazonaws.{region}.cloudformation",
            type=VPCEndpointConfig.EndpointType.INTERFACE,
            enable_private_dns=True,
        ),
        VPCEndpointConfig(
            name="EC2Endpoint",
            service_name=prefix + f"com.amazonaws.{region}.ec2",
            type=VPCEndpointConfig.EndpointType.INTERFACE,
            enable_private_dns=True,
        ),
        VPCEndpointConfig(
            name="SecretsManager",
            service_name=f"com.amazonaws.{region}.secretsmanager",
            type=VPCEndpointConfig.EndpointType.INTERFACE,
            enable_private_dns=True,
        ),
        VPCEndpointConfig(
            name="S3Endpoint",
            service_name=f"com.amazonaws.{region}.s3",
            type=VPCEndpointConfig.EndpointType.GATEWAY,
            enable_private_dns=False,
        ),
        VPCEndpointConfig(
            name="DynamoEndpoint",
            service_name=f"com.amazonaws.{region}.dynamodb",
            type=VPCEndpointConfig.EndpointType.GATEWAY,
            enable_private_dns=False,
        ),
    ]
    vpc_id = vpc_stack.cfn_outputs["VpcId"]
    subnet_id = vpc_stack.cfn_outputs["NoInternetSubnetId"]
    route_table_ids = get_route_tables(subnet_id, region)
    troposphere_template = Template()
    for vpc_endpoint in vpc_endpoints:
        vpc_endpoint_kwargs = {
            "ServiceName": vpc_endpoint.service_name,
            "PrivateDnsEnabled": vpc_endpoint.enable_private_dns,
            "VpcEndpointType": str(vpc_endpoint.type),
            "VpcId": vpc_id,
        }
        if vpc_endpoint.type == VPCEndpointConfig.EndpointType.INTERFACE:
            vpc_endpoint_kwargs["SubnetIds"] = [subnet_id]
        elif vpc_endpoint.type == VPCEndpointConfig.EndpointType.GATEWAY:
            vpc_endpoint_kwargs["RouteTableIds"] = route_table_ids
        troposphere_template.add_resource(
            VPCEndpoint(
                vpc_endpoint.name,
                **vpc_endpoint_kwargs,
            )
        )
    vpc_endpoints_stack = CfnStack(
        name=generate_stack_name("integ-tests-vpc-endpoints", request.config.getoption("stackname_suffix")),
        region=region,
        template=troposphere_template.to_json(),
    )

    cfn_stacks_factory.create_stack(vpc_endpoints_stack)
    yield
    if not request.config.getoption("no_delete"):
        cfn_stacks_factory.delete_stack(vpc_endpoints_stack.name, region)


@pytest.fixture()
def bastion_instance(vpc_stack, cfn_stacks_factory, request, region, key_name):
    """Class to create bastion instance used to execute commands on cluster in private subnet."""
    bastion_stack_name = utils.generate_stack_name(
        "integ-tests-networking-bastion", request.config.getoption("stackname_suffix")
    )

    bastion_template = Template()
    bastion_template.set_version()
    bastion_template.set_description("Create Networking bastion stack")

    bastion_sg = ec2.SecurityGroup(
        "NetworkingTestBastionSG",
        GroupDescription="SecurityGroup for Bastion",
        SecurityGroupIngress=[
            ec2.SecurityGroupRule(
                IpProtocol="tcp",
                FromPort="22",
                ToPort="22",
                CidrIp="0.0.0.0/0",
            ),
        ],
        VpcId=vpc_stack.cfn_outputs["VpcId"],
    )

    instance = ec2.Instance(
        "NetworkingBastionInstance",
        InstanceType="c5.xlarge",
        ImageId=retrieve_latest_ami(region, "alinux2"),
        KeyName=key_name,
        SecurityGroupIds=[Ref(bastion_sg)],
        SubnetId=vpc_stack.cfn_outputs["PublicSubnetId"],
    )
    bastion_template.add_resource(bastion_sg)
    bastion_template.add_resource(instance)
    bastion_template.add_output(
        Output("BastionIP", Value=GetAtt(instance, "PublicIp"), Description="The Bastion Public IP")
    )
    bastion_stack = CfnStack(
        name=bastion_stack_name,
        region=region,
        template=bastion_template.to_json(),
    )
    cfn_stacks_factory.create_stack(bastion_stack)
    bastion_ip = bastion_stack.cfn_outputs.get("BastionIP")
    logging.info(f"Bastion_ip: {bastion_ip}")

    yield f"ec2-user@{bastion_ip}"

    if not request.config.getoption("no_delete"):
        cfn_stacks_factory.delete_stack(bastion_stack_name, region)
