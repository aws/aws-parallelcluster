# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import boto3
import pytest

from remote_command_executor import RemoteCommandExecutor
from tests.common.schedulers_common import get_scheduler_commands

OS_TO_AMI_NAME_OWNER_MAP = {
    "alinux": {"name": "amzn-ami-hvm-*.*.*.*-x86_64-gp2", "owners": ["amazon"]},
    "alinux2": {"name": "amzn2-ami-hvm-*.*.*.*-x86_64-gp2", "owners": ["amazon"]},
    "centos6": {"name": "CentOS 6.x x86_64 - minimal with cloud-init - *", "owners": ["247102896272"]},
    "centos7": {"name": "CentOS Linux 7 x86_64 HVM EBS ENA *", "owner": ["410186602215"]},
    "ubuntu1604": {
        "name": "ubuntu/images/hvm-ssd/ubuntu-xenial-16.04-amd64-server-*",
        "owners": ["099720109477", "513442679011", "837727238323"],
    },
    "ubuntu1804": {
        "name": "ubuntu/images/hvm-ssd/ubuntu-bionic-18.04-amd64-server-*",
        "owners": ["099720109477", "513442679011", "837727238323"],
    },
}


def _check_no_chef_install(scheduler, remote_command_executor, test_datadir):
    """Verify no chef.io endpoint is called in cloud-init-output log to download chef installer or chef packages"""
    # On master
    remote_command_executor.run_remote_script(str(test_datadir / "verify_no_chef_install.sh"))
    # On compute
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    result = scheduler_commands.submit_script(str(test_datadir / "verify_no_chef_install.sh"))
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)


def _check_chef_s3(scheduler, remote_command_executor, test_datadir):
    """Verify no chef.io endpoint is called in cloud-init-output log to download chef installer or chef packages"""
    # On master
    remote_command_executor.run_remote_script(str(test_datadir / "verify_chef_s3.sh"))
    # On compute
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    result = scheduler_commands.submit_script(str(test_datadir / "verify_chef_s3.sh"))
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)


def _check_chef_official(scheduler, remote_command_executor, test_datadir):
    """Verify no chef.io endpoint is called in cloud-init-output log to download chef installer or chef packages"""
    # On master
    remote_command_executor.run_remote_script(str(test_datadir / "verify_chef_official.sh"))
    # On compute
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    result = scheduler_commands.submit_script(str(test_datadir / "verify_chef_official.sh"))
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)


def _retrieve_latest_ami(region, os):
    ec2_client = boto3.client("ec2", region_name=region)
    response = ec2_client.describe_images(
        Filters=[{"Name": "name", "Values": [OS_TO_AMI_NAME_OWNER_MAP[os]["name"]]}],
        Owners=OS_TO_AMI_NAME_OWNER_MAP[os]["owners"],
    )
    # Sort on Creation date Desc
    amis = sorted(response["Images"], key=lambda x: x["CreationDate"], reverse=True)
    return amis[0]["ImageId"]


@pytest.mark.skip_dimensions("cn-north-1", "*", "centos6", "*")
@pytest.mark.skip_dimensions("cn-northwest-1", "*", "centos7", "*")
@pytest.mark.skip_dimensions("us-gov-east-1", "*", "centos6", "*")
@pytest.mark.skip_dimensions("us-gov-west-1", "*", "centos7", "*")
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["torque"])
@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
@pytest.mark.chef_official
def test_chef_official(scheduler, os, region, pcluster_config_reader, clusters_factory, test_datadir):
    """Test that a cluster download chef from official location."""
    cluster_config = pcluster_config_reader(custom_ami=_retrieve_latest_ami(region, os))
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # Ensure chef.io endpoint is called to download chef installer or chef packages
    _check_chef_official(scheduler, remote_command_executor, test_datadir)


@pytest.mark.skip_dimensions("cn-north-1", "*", "centos6", "*")
@pytest.mark.skip_dimensions("cn-northwest-1", "*", "centos7", "*")
@pytest.mark.skip_dimensions("us-gov-east-1", "*", "centos6", "*")
@pytest.mark.skip_dimensions("us-gov-west-1", "*", "centos7", "*")
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm"])
@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
@pytest.mark.chef_s3
def test_chef_s3(scheduler, os, region, pcluster_config_reader, clusters_factory, test_datadir):
    """Test that a cluster download chef from ParallelCluster S3."""
    cluster_config = pcluster_config_reader(custom_ami=_retrieve_latest_ami(region, os))
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # Ensure no chef.io endpoint is called to download chef installer or chef packages
    _check_chef_s3(scheduler, remote_command_executor, test_datadir)


@pytest.mark.skip_dimensions("cn-north-1", "*", "centos6", "*")
@pytest.mark.skip_dimensions("cn-northwest-1", "*", "centos7", "*")
@pytest.mark.skip_dimensions("us-gov-east-1", "*", "centos6", "*")
@pytest.mark.skip_dimensions("us-gov-west-1", "*", "centos7", "*")
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["sge"])
@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
@pytest.mark.no_chef_install
def test_no_chef_install(scheduler, pcluster_config_reader, clusters_factory, test_datadir):
    """Test that a cluster does not install chef"""
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # Ensure no chef.io endpoint is called to download chef installer or chef packages
    _check_no_chef_install(scheduler, remote_command_executor, test_datadir)
