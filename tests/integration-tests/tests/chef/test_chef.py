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
import logging

import boto3
import pytest

from assertpy import assert_that
from packaging import version
from remote_command_executor import RemoteCommandExecutor
from tests.common.schedulers_common import get_scheduler_commands
from utils import run_command

OS_TO_AMI_NAME_OWNER_MAP = {
    "alinux": {"name": "amzn-ami-hvm-*.*.*.*-x86_64-gp2", "owners": ["amazon"]},
    "alinux2": {"name": "amzn2-ami-hvm-*.*.*.*-x86_64-gp2", "owners": ["amazon"]},
    "centos6": {"name": "CentOS 6.x x86_64 - minimal with cloud-init - *", "owners": ["247102896272"]},
    "centos7": {"name": "CentOS Linux 7 x86_64 HVM EBS ENA *", "owners": ["410186602215"]},
    "ubuntu1404": {
        "name": "ubuntu/images/hvm-ssd/ubuntu-trusty-14.04-amd64-server-*",
        "owners": ["099720109477", "513442679011", "837727238323"],
    },
    "ubuntu1604": {
        "name": "ubuntu/images/hvm-ssd/ubuntu-xenial-16.04-amd64-server-*",
        "owners": ["099720109477", "513442679011", "837727238323"],
    },
    "ubuntu1804": {
        "name": "ubuntu/images/hvm-ssd/ubuntu-bionic-18.04-amd64-server-*",
        "owners": ["099720109477", "513442679011", "837727238323"],
    },
}

OS_TO_CUSTOM_AMI_NAME_OWNER_MAP = {
    "alinux": {"name": "Deep Learning Base AMI (Amazon Linux)*", "owners": ["amazon"]},
    "alinux2": {"name": "Deep Learning Base AMI (Amazon Linux 2)*", "owners": ["amazon"]},
    "centos6": {"name": "CentOS 6.x x86_64 - minimal with cloud-init - *", "owners": ["247102896272"]},
    "centos7": {"name": "FPGA Developer AMI*", "owners": ["679593333241"]},
    "ubuntu1604": {"name": "Deep Learning Base AMI (Ubuntu 16.04)*", "owners": ["amazon"]},
    "ubuntu1804": {"name": "Deep Learning Base AMI (Ubuntu 18.04)*", "owners": ["amazon"]},
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


@pytest.mark.skip_dimensions("cn-north-1", "*", "centos6", "*")
@pytest.mark.skip_dimensions("cn-northwest-1", "*", "centos7", "*")
@pytest.mark.skip_dimensions("us-gov-east-1", "*", "centos6", "*")
@pytest.mark.skip_dimensions("us-gov-west-1", "*", "centos7", "*")
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.create_ami
def test_create_ami(region, os, instance, request, pcluster_config_reader):
    """Test createami for given region and os"""
    cluster_config = pcluster_config_reader()
    base_ami = _retrieve_latest_ami(region, os)
    custom_cookbook = request.config.getoption("custom_chef_cookbook")
    cc_args = [] if not custom_cookbook else ["-cc", custom_cookbook]

    pcluster_version_result = run_command(["pcluster", "version"])
    i_args = [] if version.parse(pcluster_version_result.stdout.strip()) < version.parse("2.4.1") else ["-i", instance]

    pcluster_createami_result = run_command(
        ["pcluster", "createami", "-ai", base_ami, "-os", os, "-r", region, "-c", cluster_config.as_posix()]
        + cc_args
        + i_args
    )

    logging.info(pcluster_createami_result.stdout)
    assert_that(
        any(
            "downloading https://{0}-aws-parallelcluster.s3.{1}.amazonaws.com{2}/packages/chef/chef".format(
                region, region, "" if not region.startswith("cn-") else ".cn"
            ).lower()
            in s.lower()
            for s in pcluster_createami_result.stdout.split("\n")
        )
    ).is_true()
    assert_that(
        any("packages.chef.io".lower() in s.lower() for s in pcluster_createami_result.stdout.split("\n"))
    ).is_false()
    assert_that(
        any("Thank you for installing Chef".lower() in s.lower() for s in pcluster_createami_result.stdout.split("\n"))
    ).is_true()

    # Not testing AMI creation
    # assert_that(pcluster_createami_result.stdout).does_not_contain("No custom AMI created")


@pytest.mark.skip_dimensions("cn-north-1", "*", "centos6", "*")
@pytest.mark.skip_dimensions("cn-northwest-1", "*", "centos7", "*")
@pytest.mark.skip_dimensions("us-gov-east-1", "*", "centos6", "*")
@pytest.mark.skip_dimensions("us-gov-west-1", "*", "centos7", "*")
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.official_chef_create_ami
def test_official_chef_create_ami(region, os, instance, request, pcluster_config_reader):
    """Test createami for given region and os"""
    cluster_config = pcluster_config_reader()
    base_ami = _retrieve_latest_ami(region, os)
    custom_cookbook = request.config.getoption("custom_chef_cookbook")
    cc_args = [] if not custom_cookbook else ["-cc", custom_cookbook]

    pcluster_version_result = run_command(["pcluster", "version"])
    i_args = [] if version.parse(pcluster_version_result.stdout.strip()) < version.parse("2.4.1") else ["-i", instance]

    pcluster_createami_result = run_command(
        ["pcluster", "createami", "-ai", base_ami, "-os", os, "-r", region, "-c", cluster_config.as_posix()]
        + cc_args
        + i_args
    )

    logging.info(pcluster_createami_result.stdout)

    # Test Chef installed from official repo
    assert_that(
        any("packages.chef.io".lower() in s.lower() for s in pcluster_createami_result.stdout.split("\n"))
    ).is_true()
    assert_that(
        any("Thank you for installing Chef".lower() in s.lower() for s in pcluster_createami_result.stdout.split("\n"))
    ).is_true()
