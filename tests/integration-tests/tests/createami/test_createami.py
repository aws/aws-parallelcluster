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

import pytest
from assertpy import assert_that
from packaging import version
from utils import run_command

from tests.common.utils import retrieve_latest_ami


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
    ami_type = "remarkable"
    base_ami = retrieve_latest_ami(region, os, ami_type=ami_type, architecture=architecture)
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

    assert_that(
        any(
            "downloading https://{0}-aws-parallelcluster.s3".format(region).lower() in s.lower()
            for s in pcluster_createami_result.stdout.split("\n")
        )
    ).is_true()
    assert_that(
        any("chef.io/chef/install.sh".lower() in s.lower() for s in pcluster_createami_result.stdout.split("\n"))
    ).is_false()
    assert_that(
        any("packages.chef.io".lower() in s.lower() for s in pcluster_createami_result.stdout.split("\n"))
    ).is_false()
    assert_that(
        any(
            "Thank you for installing Cinc Client".lower() in s.lower()
            for s in pcluster_createami_result.stdout.split("\n")
        )
    ).is_true()
    assert_that(
        any("Starting Cinc Client".lower() in s.lower() for s in pcluster_createami_result.stdout.split("\n"))
    ).is_true()

    assert_that(pcluster_createami_result.stdout).does_not_contain("No custom AMI created")


@pytest.mark.dimensions("us-west-2", "c5.xlarge", "centos7", "*")
@pytest.mark.dimensions("eu-west-2", "c5.xlarge", "ubuntu1804", "*")
@pytest.mark.dimensions("eu-west-1", "m6g.xlarge", "alinux2", "*")
def test_createami_post_install(
    region, os, instance, test_datadir, request, pcluster_config_reader, vpc_stack, architecture
):
    """Test post install script and base AMI is ParallelCluster AMI"""
    cluster_config = pcluster_config_reader()

    # Get ParallelCluster AMI as base AMI
    ami_type = "pcluster"
    base_ami = retrieve_latest_ami(region, os, ami_type=ami_type, architecture=architecture)

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

    # Post install script
    post_install_script = (
        "file://" + str(test_datadir / "post_install_ubuntu.sh")
        if os == "ubuntu1804" or os == "ubuntu1604"
        else "file://" + str(test_datadir / "post_install.sh")
    )
    post_install_args = ["--post-install", post_install_script]

    pcluster_createami_result = run_command(
        ["pcluster", "createami", "-ai", base_ami, "-os", os, "-r", region, "-c", cluster_config.as_posix()]
        + custom_cookbook_args
        + instance_args
        + networking_args
        + post_install_args
    )

    assert_that(
        any(
            "downloading https://{0}-aws-parallelcluster.s3".format(region).lower() in s.lower()
            for s in pcluster_createami_result.stdout.split("\n")
        )
    ).is_true()
    assert_that(
        any("No post script".lower() in s.lower() for s in pcluster_createami_result.stdout.split("\n"))
    ).is_false()

    assert_that(pcluster_createami_result.stdout).does_not_contain("No custom AMI created")
