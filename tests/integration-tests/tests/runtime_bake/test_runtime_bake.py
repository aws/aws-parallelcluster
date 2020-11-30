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
from remote_command_executor import RemoteCommandExecutor

from tests.common.schedulers_common import get_scheduler_commands
from tests.common.utils import retrieve_latest_ami


@pytest.mark.skip(reason="Temporarily disable this test")
@pytest.mark.dimensions("eu-west-2", "c5.xlarge", "alinux", "slurm")
@pytest.mark.dimensions("eu-west-3", "c5.xlarge", "alinux2", "torque")
@pytest.mark.dimensions("us-east-2", "c5.xlarge", "centos7", "sge")
@pytest.mark.dimensions("us-east-2", "c5.xlarge", "centos8", "sge")
@pytest.mark.dimensions("us-east-1", "c5.xlarge", "ubuntu1604", "slurm")
@pytest.mark.dimensions("eu-west-1", "c5.xlarge", "ubuntu1804", "sge")
@pytest.mark.dimensions("us-gov-east-1", "c5.xlarge", "ubuntu1604", "slurm")
@pytest.mark.dimensions("us-gov-west-1", "c5.xlarge", "ubuntu1804", "sge")
@pytest.mark.dimensions("us-east-1", "m6g.xlarge", "ubuntu1804", "sge")
@pytest.mark.dimensions("eu-west-1", "m6g.xlarge", "alinux2", "slurm")
@pytest.mark.usefixtures("instance", "scheduler")
def test_runtime_bake(scheduler, os, region, pcluster_config_reader, clusters_factory, test_datadir, architecture):
    """Test cluster creation with runtime bake."""
    # remarkable AMIs are not available for ARM yet
    ami_type = "remarkable" if architecture == "x86_64" else "official"
    cluster_config = pcluster_config_reader(
        custom_ami=retrieve_latest_ami(region, os, ami_type=ami_type, architecture=architecture)
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # Verify no chef.io endpoint is called in cloud-init-output log to download chef installer or chef packages"""
    # on head node
    remote_command_executor.run_remote_script(str(test_datadir / "verify_chef_download.sh"))
    # on compute
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    result = scheduler_commands.submit_script(str(test_datadir / "verify_chef_download.sh"))
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
