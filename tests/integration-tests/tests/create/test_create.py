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

from tests.common.assertions import assert_errors_in_logs
from tests.common.utils import (
    get_installed_parallelcluster_version,
    retrieve_latest_ami,
    retrieve_pcluster_ami_without_standard_naming,
)


@pytest.mark.dimensions("eu-central-1", "c5.xlarge", "ubuntu1804", "*")
def test_create_wrong_os(region, os, pcluster_config_reader, clusters_factory, architecture, instance):
    """Test error message when os provide is different from the os of custom AMI"""
    # ubuntu1804 is specified in the config file but an AMI of centos7 is provided
    wrong_os = "centos7"
    logging.info("Asserting os fixture is different from wrong_os variable")
    assert_that(os != wrong_os).is_true()
    custom_ami = retrieve_latest_ami(region, wrong_os, ami_type="remarkable", architecture=architecture)
    cluster_config = pcluster_config_reader(custom_ami=custom_ami)
    cluster = clusters_factory(cluster_config, raise_on_error=False)
    username = get_username_for_os(wrong_os)
    remote_command_executor = RemoteCommandExecutor(cluster, username=username)

    logging.info("Verifying error in logs")
    assert_errors_in_logs(
        remote_command_executor,
        ["/var/log/cfn-init.log"],
        ["RuntimeError", fr"custom AMI.+{wrong_os}.+base.+os.+config file.+{os}"],
    )


@pytest.mark.dimensions("ca-central-1", "c5.xlarge", "alinux", "*")
def test_create_wrong_pcluster_version(region, os, pcluster_config_reader, clusters_factory, architecture, instance):
    """Test error message when AMI provided was baked by a pcluster whose version is different from current version"""
    current_version = get_installed_parallelcluster_version()
    wrong_version = "2.8.1"
    logging.info("Asserting wrong_version is different from current_version")
    assert_that(current_version != wrong_version).is_true()
    # Retrieve an AMI without 'aws-parallelcluster-<version>' in its name.
    # Therefore, we can bypass the version check in CLI and test version check of .bootstrapped file in Cookbook.
    wrong_ami = retrieve_pcluster_ami_without_standard_naming(
        region, os, version=wrong_version, architecture=architecture
    )
    cluster_config = pcluster_config_reader(custom_ami=wrong_ami)
    cluster = clusters_factory(cluster_config, raise_on_error=False)
    remote_command_executor = RemoteCommandExecutor(cluster)

    logging.info("Verifying error in logs")
    assert_errors_in_logs(
        remote_command_executor,
        ["/var/log/cfn-init.log"],
        ["RuntimeError", fr"AMI was created.+{wrong_version}.+is.+used.+{current_version}"],
    )
