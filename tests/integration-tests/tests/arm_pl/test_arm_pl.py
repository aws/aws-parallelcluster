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


@pytest.mark.regions(["ap-northeast-1"])
@pytest.mark.instances(["m6g.xlarge"])
@pytest.mark.oss(["ubuntu1804", "alinux2", "centos8"])
@pytest.mark.schedulers(["slurm"])
def test_arm_pl(region, scheduler, instance, os, pcluster_config_reader, clusters_factory, test_datadir):
    """Test Arm Performance Library"""
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # arm performance library version and gcc version
    armpl_version = "20.2.1"
    gcc_version = "9.3"

    # loading module armpl/{armpl_version} will load module armpl/gcc-{gcc_version}
    # and armpl/{armpl_version}_gcc-{gcc_vesion}  sequentially
    armpl_module_general_name = f"armpl/{armpl_version}"
    armpl_module_name = f"armpl/{armpl_version}_gcc-{gcc_version}"
    gcc_module_name = f"armpl/gcc-{gcc_version}"
    _test_armpl_examples(
        remote_command_executor,
        armpl_module_general_name,
        armpl_module_name,
        gcc_module_name,
        armpl_version,
        gcc_version,
    )


def _test_armpl_examples(
    remote_command_executor, armpl_module_general_name, armpl_module_name, gcc_module_name, armpl_version, gcc_version
):
    # Test arm performance library examples to check arm performance library is available in cluster
    logging.info("Test arm performance library examples")

    # Load armpl module and gcc-9.3 module and assert module loaded
    module_result = remote_command_executor.run_remote_command(
        f"module load {armpl_module_general_name} && module list"
    ).stdout
    for module in [armpl_module_general_name, armpl_module_name, gcc_module_name]:
        assert_that(module_result).contains(module)

    # Assert pass the example tests
    remote_command_executor.run_remote_command(
        f"sudo chmod 777 /opt/arm/armpl/{armpl_version}/armpl_{armpl_version}_gcc-{gcc_version}/examples"
    )
    test_result = remote_command_executor.run_remote_command(
        f"module load {armpl_module_general_name} && "
        f"cd /opt/arm/armpl/{armpl_version}/armpl_{armpl_version}_gcc-{gcc_version}/examples && make clean && make"
    ).stdout.lower()
    assert_that(test_result).contains("testing: no example difference files were generated")
    assert_that(test_result).contains("test passed ok")
