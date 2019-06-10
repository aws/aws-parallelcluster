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
import pytest

from remote_command_executor import RemoteCommandExecutor
from tests.common.mpi_common import _test_mpi
from tests.common.utils import _fetch_instance_slots


@pytest.mark.regions(["us-west-2"])
@pytest.mark.instances(["c5.xlarge", "c5n.18xlarge"])
@pytest.mark.schedulers(["slurm", "sge"])
@pytest.mark.oss(["alinux", "centos7", "centos6", "ubuntu1604", "ubuntu1804"])
def test_mpi(scheduler, region, os, instance, pcluster_config_reader, clusters_factory):
    scaledown_idletime = 3
    max_queue_size = 3
    slots_per_instance = _fetch_instance_slots(region, instance)
    cluster_config = pcluster_config_reader(scaledown_idletime=scaledown_idletime, max_queue_size=max_queue_size)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # This verifies that scaling worked
    _test_mpi(
        remote_command_executor,
        slots_per_instance,
        scheduler,
        os,
        region,
        cluster.cfn_name,
        scaledown_idletime,
        verify_scaling=True,
    )

    # This verifies that the job completes correctly
    _test_mpi(
        remote_command_executor,
        slots_per_instance,
        scheduler,
        os,
        region,
        cluster.cfn_name,
        scaledown_idletime,
        verify_scaling=False,
    )
