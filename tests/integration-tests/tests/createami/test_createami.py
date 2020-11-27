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
from os import environ

import pytest
from assertpy import assert_that
from packaging import version
from utils import run_command

from tests.common.utils import get_installed_parallelcluster_version, retrieve_latest_ami


@pytest.mark.dimensions("eu-west-1", "c5.xlarge", "alinux", "*")
@pytest.mark.dimensions("us-west-1", "c5.xlarge", "alinux2", "*")
@pytest.mark.dimensions("us-west-2", "c5.xlarge", "centos7", "*")
@pytest.mark.dimensions("us-west-2", "c5.xlarge", "centos8", "*")
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

    # Custom Node
    # inject PARALLELCLUSTER_NODE_URL into packer environment
    custom_node = request.config.getoption("createami_custom_node_package")
    env = None
    if custom_node:
        env = environ.copy()
        env["PARALLELCLUSTER_NODE_URL"] = custom_node

    # Instance type
    pcluster_version_result = run_command(["pcluster", "version"])
    instance_args = (
        [] if version.parse(pcluster_version_result.stdout.strip()) < version.parse("2.4.1") else ["-i", instance]
    )

    pcluster_createami_result = run_command(
        ["pcluster", "createami", "-ai", base_ami, "-os", os, "-r", region, "-c", cluster_config.as_posix()]
        + custom_cookbook_args
        + instance_args
        + networking_args,
        env=env,
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
def test_createami_wrong_os(region, instance, os, request, pcluster_config_reader, vpc_stack, architecture):
    """Test error message when os provide is different from the os of custom AMI"""
    cluster_config = pcluster_config_reader()

    # alinux is specified in the config file but an AMI of alinux2 is provided
    wrong_os = "alinux2"
    logging.info("Asserting os fixture is different from wrong_os variable")
    assert_that(os != wrong_os).is_true()
    base_ami = retrieve_latest_ami(region, wrong_os, ami_type="pcluster", architecture=architecture)

    command = _compose_command(region, instance, os, request, vpc_stack, base_ami, cluster_config)
    _createami_and_assert_error(command, fr"custom AMI.+{wrong_os}.+base.+os.+config file.+{os}")


@pytest.mark.dimensions("ca-central-1", "c5.xlarge", "alinux", "*")
def test_createami_wrong_pcluster_version(
    region, instance, os, request, pcluster_config_reader, vpc_stack, pcluster_ami_without_standard_naming
):
    """Test error message when AMI provided was baked by a pcluster whose version is different from current version"""
    cluster_config = pcluster_config_reader()
    current_version = get_installed_parallelcluster_version()
    wrong_version = "2.8.1"
    logging.info("Asserting wrong_version is different from current_version")
    assert_that(current_version != wrong_version).is_true()
    # Retrieve an AMI without 'aws-parallelcluster-<version>' in its name.
    # Therefore, we can bypass the version check in CLI and test version check of .bootstrapped file in Cookbook.
    wrong_ami = pcluster_ami_without_standard_naming(wrong_version)

    command = _compose_command(region, instance, os, request, vpc_stack, wrong_ami, cluster_config)
    _createami_and_assert_error(command, fr"AMI was created.+{wrong_version}.+is.+used.+{current_version}")


def _compose_command(region, instance, os, request, vpc_stack, base_ami, cluster_config):
    # Networking
    vpc_id = vpc_stack.cfn_outputs["VpcId"]
    networking_args = ["--vpc-id", vpc_id, "--subnet-id", vpc_stack.cfn_outputs["PublicSubnetId"]]

    # Custom Cookbook
    custom_cookbook = request.config.getoption("createami_custom_chef_cookbook")
    custom_cookbook_args = [] if not custom_cookbook else ["-cc", custom_cookbook]

    return (
        [
            "pcluster",
            "createami",
            "-ai",
            base_ami,
            "-os",
            os,
            "-r",
            region,
            "-c",
            cluster_config.as_posix(),
            "-i",
            instance,
        ]
        + custom_cookbook_args
        + networking_args
    )


def _createami_and_assert_error(command, expected_error):
    pcluster_createami_result = run_command(command, raise_on_error=False)

    logging.info("Verifying errors in createami stdout and packer log")
    stdout = pcluster_createami_result.stdout
    packer_log_path = _get_packer_log_path(stdout)
    with open(packer_log_path) as f:
        packer_log = f.read()
    logging.info(packer_log)
    assert_that(packer_log).contains("RuntimeError")
    assert_that(packer_log).matches(expected_error)
    assert_that(stdout).contains("No custom AMI created")


def _get_packer_log_path(createami_stdout):
    packer_log_key = "Packer log: "
    for line in createami_stdout.split("\n"):
        if line.startswith(packer_log_key):
            packer_log_key_len = len(packer_log_key)
            return line[packer_log_key_len:]
    logging.error("Packer log path is not found in stdout of createami")
    raise Exception
