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

import pexpect
import pytest
from assertpy import assert_that
from packaging import version
from utils import run_command

from tests.common.utils import (
    get_installed_parallelcluster_version,
    retrieve_latest_ami,
    retrieve_pcluster_ami_without_standard_naming,
)


@pytest.mark.dimensions("eu-west-1", "c5.xlarge", "alinux", "*")
@pytest.mark.dimensions("us-west-1", "c5.xlarge", "alinux2", "*")
@pytest.mark.dimensions("us-west-2", "c5.xlarge", "centos7", "*")
@pytest.mark.dimensions("eu-west-2", "c5.xlarge", "ubuntu1604", "*")
@pytest.mark.dimensions("us-east-1", "c5.xlarge", "ubuntu1804", "*")
@pytest.mark.dimensions("us-gov-east-1", "c5.xlarge", "ubuntu1604", "*")
@pytest.mark.dimensions("us-gov-west-1", "c5.xlarge", "ubuntu1804", "*")
@pytest.mark.dimensions("cn-northwest-1", "c4.xlarge", "alinux2", "*")
def test_createami(region, os, instance, request, pcluster_config_reader, vpc_stack, architecture):
    """Test createami for given region and os"""
    cluster_config = pcluster_config_reader()

    # Get base AMI
    # remarkable AMIs are not available for ARM yet
    base_ami = retrieve_latest_ami(region, os, ami_type="remarkable", architecture=architecture)

    # Networking
    vpc_id = vpc_stack.cfn_outputs["VpcId"]
    networking_args = ["--vpc-id", vpc_id, "--subnet-id", vpc_stack.cfn_outputs["PublicSubnetId"]]

    # Custom Cookbook
    custom_cookbook = request.config.getoption("createami_custom_chef_cookbook")
    custom_cookbook_args = [] if not custom_cookbook else ["-cc", custom_cookbook]

    # Instance type
    pcluster_version_result = run_command(["pcluster", "version"])
    instance_args = (
        [] if version.parse(pcluster_version_result.stdout.strip()) < version.parse("2.4.1") else ["-i", instance]
    )

    pcluster_createami_result = run_command(
        ["pcluster", "createami", "-ai", base_ami, "-os", os, "-r", region, "-c", cluster_config.as_posix()]
        + custom_cookbook_args
        + instance_args
        + networking_args
    )

    stdout_lower = pcluster_createami_result.stdout.lower()
    assert_that(stdout_lower).contains("downloading https://{0}-aws-parallelcluster.s3".format(region))
    assert_that(stdout_lower).does_not_contain("chef.io/chef/install.sh")
    assert_that(stdout_lower).does_not_contain("packages.chef.io")
    assert_that(stdout_lower).contains("thank you for installing cinc client")
    assert_that(stdout_lower).contains("starting cinc client")
    assert_that(stdout_lower).does_not_contain("no custom ami created")


@pytest.mark.dimensions("us-west-2", "c5.xlarge", "centos7", "*")
@pytest.mark.dimensions("eu-west-2", "c5.xlarge", "ubuntu1804", "*")
@pytest.mark.dimensions("eu-west-1", "m6g.xlarge", "alinux2", "*")
def test_createami_post_install(
    region, os, instance, test_datadir, request, pcluster_config_reader, vpc_stack, architecture
):
    """Test post install script and base AMI is ParallelCluster AMI"""
    cluster_config = pcluster_config_reader()

    # Get ParallelCluster AMI as base AMI
    base_ami = retrieve_latest_ami(region, os, ami_type="pcluster", architecture=architecture)

    # Networking
    vpc_id = vpc_stack.cfn_outputs["VpcId"]
    networking_args = ["--vpc-id", vpc_id, "--subnet-id", vpc_stack.cfn_outputs["PublicSubnetId"]]

    # Custom Cookbook
    custom_cookbook = request.config.getoption("createami_custom_chef_cookbook")
    custom_cookbook_args = [] if not custom_cookbook else ["-cc", custom_cookbook]

    # Instance type
    instance_args = ["-i", instance]

    # Post install script
    post_install_script_file = "post_install_ubuntu.sh" if os in ["ubuntu1804", "ubuntu1604"] else "post_install.sh"
    post_install_script = "file://{0}".format(test_datadir / post_install_script_file)
    post_install_args = ["--post-install", post_install_script]

    pcluster_createami_result = run_command(
        ["pcluster", "createami", "-ai", base_ami, "-os", os, "-r", region, "-c", cluster_config.as_posix()]
        + custom_cookbook_args
        + instance_args
        + networking_args
        + post_install_args
    )

    stdout_lower = pcluster_createami_result.stdout.lower()
    assert_that(stdout_lower).does_not_contain("no post install script")
    assert_that(stdout_lower).does_not_contain("no custom ami created")


@pytest.mark.dimensions("eu-central-1", "c5.xlarge", "alinux", "*")
def test_createami_wrong_os(region, os, instance, request, pcluster_config_reader, vpc_stack, architecture):
    """Test error message when os provide is different from the os of custom AMI"""
    cluster_config = pcluster_config_reader()

    # alinux is specified in the config file but an AMI of alinux2 is provided
    wrong_os = "alinux2"
    logging.info("Asserting os fixture is different from wrong_os variable")
    assert_that(os != wrong_os).is_true()
    base_ami = retrieve_latest_ami(region, wrong_os, ami_type="pcluster", architecture=architecture)

    # Networking
    vpc_id = vpc_stack.cfn_outputs["VpcId"]
    subnet_id = vpc_stack.cfn_outputs["PublicSubnetId"]
    networking_args = f"--vpc-id {vpc_id} --subnet-id {subnet_id}"

    # Custom Cookbook
    custom_cookbook = request.config.getoption("createami_custom_chef_cookbook")
    custom_cookbook_args = "" if not custom_cookbook else f"-cc {custom_cookbook}"

    command = (
        f"pcluster createami -ai {base_ami} -os {os} -r {region} -c {cluster_config.as_posix()} "
        f"{custom_cookbook_args} -i {instance} {networking_args}"
    )
    createami_process = pexpect.spawn(command, timeout=600)
    logging.info("Verifying errors in stdout")
    createami_process.expect("RuntimeError")
    createami_process.expect(fr"custom AMI.+{wrong_os}.+base.+os.+config file.+{os}")
    createami_process.expect("No custom AMI created")
    createami_process.close()


@pytest.mark.dimensions("ca-central-1", "c5.xlarge", "alinux", "*")
def test_createami_wrong_pcluster_version(
    region, os, instance, request, pcluster_config_reader, vpc_stack, architecture
):
    """Test error message when AMI provided was baked by a pcluster whose version is different from current version"""
    cluster_config = pcluster_config_reader()
    current_version = get_installed_parallelcluster_version()
    wrong_version = "2.8.1"
    logging.info("Asserting wrong_version is different from current_version")
    assert_that(current_version != wrong_version).is_true()
    # Retrieve an AMI without 'aws-parallelcluster-<version>' in its name.
    # Therefore, we can bypass the version check in CLI and test version check of .bootstrapped file in Cookbook.
    wrong_ami = retrieve_pcluster_ami_without_standard_naming(
        region, os, version=wrong_version, architecture=architecture
    )
    # Networking
    vpc_id = vpc_stack.cfn_outputs["VpcId"]
    subnet_id = vpc_stack.cfn_outputs["PublicSubnetId"]
    networking_args = f"--vpc-id {vpc_id} --subnet-id {subnet_id}"

    # Custom Cookbook
    custom_cookbook = request.config.getoption("createami_custom_chef_cookbook")
    custom_cookbook_args = "" if not custom_cookbook else f"-cc {custom_cookbook}"

    command = (
        f"pcluster createami -ai {wrong_ami} -os {os} -r {region} -c {cluster_config.as_posix()} "
        f"{custom_cookbook_args} -i {instance} {networking_args}"
    )
    createami_process = pexpect.spawn(command, timeout=600)
    logging.info("Verifying errors in stdout")
    createami_process.expect("RuntimeError")
    createami_process.expect(fr"AMI was created.+{wrong_version}.+is.+used.+{os}")
    createami_process.expect("No custom AMI created")
    createami_process.close()
