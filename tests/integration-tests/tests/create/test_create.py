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

import pytest
from assertpy import assert_that
from remote_command_executor import RemoteCommandExecutor
from utils import get_username_for_os

from tests.common.assertions import (
    assert_aws_identity_access_is_correct,
    assert_cluster_imds_v2_requirement_status,
    assert_head_node_is_running,
    assert_lines_in_logs,
)
from tests.common.utils import get_installed_parallelcluster_version, reboot_head_node, retrieve_latest_ami


@pytest.mark.usefixtures("instance", "scheduler")
def test_create_wrong_os(region, os, pcluster_config_reader, clusters_factory, architecture, request):
    """Test error message when os provide is different from the os of custom AMI"""
    # ubuntu1804 is specified in the config file but an AMI of ubuntu2004 is provided
    wrong_os = "ubuntu2004"
    logging.info("Asserting os fixture is different from wrong_os variable")
    assert_that(os != wrong_os).is_true()
    custom_ami = retrieve_latest_ami(region, wrong_os, ami_type="pcluster", architecture=architecture, request=request)
    cluster_config = pcluster_config_reader(custom_ami=custom_ami)
    cluster = clusters_factory(cluster_config, raise_on_error=False)

    assert_head_node_is_running(region, cluster)
    username = get_username_for_os(wrong_os)
    remote_command_executor = RemoteCommandExecutor(cluster, username=username)

    logging.info("Verifying error in logs")
    assert_lines_in_logs(
        remote_command_executor,
        ["/var/log/chef-client.log"],
        ["RuntimeError", rf"custom AMI.+{wrong_os}.+base.+os.+config file.+{os}"],
    )


@pytest.mark.usefixtures("instance", "os", "scheduler")
def test_create_wrong_pcluster_version(
    region, pcluster_config_reader, pcluster_ami_without_standard_naming, clusters_factory
):
    """Test error message when AMI provided was baked by a pcluster whose version is different from current version"""
    current_version = get_installed_parallelcluster_version()
    wrong_version = "2.8.1"
    logging.info("Asserting wrong_version is different from current_version")
    assert_that(current_version != wrong_version).is_true()
    # Retrieve an AMI without 'aws-parallelcluster-<version>' in its name.
    # Therefore, we can bypass the version check in CLI and test version check of .bootstrapped file in Cookbook.
    wrong_ami = pcluster_ami_without_standard_naming(wrong_version)
    cluster_config = pcluster_config_reader(custom_ami=wrong_ami)
    cluster = clusters_factory(cluster_config, raise_on_error=False)

    assert_head_node_is_running(region, cluster)
    remote_command_executor = RemoteCommandExecutor(cluster)

    logging.info("Verifying error in logs")
    assert_lines_in_logs(
        remote_command_executor,
        ["/var/log/cloud-init-output.log"],
        ["error_exit", rf"AMI was created.+{wrong_version}.+is.+used.+{current_version}"],
    )


@pytest.mark.usefixtures("instance", "scheduler")
@pytest.mark.parametrize(
    "imds_secured, users_allow_list, imds_support",
    [
        (True, {"root": True, "pcluster-admin": True, "slurm": False}, "v2.0"),
        (False, {"root": True, "pcluster-admin": True, "slurm": True}, "v1.0"),
    ],
)
def test_create_imds_secured(
    imds_secured, users_allow_list, imds_support, region, os, pcluster_config_reader, clusters_factory, architecture
):
    """
    Test IMDS access with different configurations.
    In particular, it also verifies that IMDS access is preserved on instance reboot.
    Also checks that the cluster instances respect the desired ImdsSupport setting.
    """
    cluster_config = pcluster_config_reader(imds_secured=imds_secured, imds_support=imds_support)
    cluster = clusters_factory(cluster_config, raise_on_error=True)
    status = "required" if imds_support == "v2.0" else "optional"

    assert_head_node_is_running(region, cluster)
    assert_aws_identity_access_is_correct(cluster, users_allow_list)
    assert_cluster_imds_v2_requirement_status(region, cluster, status)

    reboot_head_node(cluster)

    assert_head_node_is_running(region, cluster)
    assert_aws_identity_access_is_correct(cluster, users_allow_list)
    assert_cluster_imds_v2_requirement_status(region, cluster, status)
