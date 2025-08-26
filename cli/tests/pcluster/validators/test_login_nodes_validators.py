# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import pytest
import yaml
from assertpy import assert_that

from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.validators.common import FailureLevel
from tests.pcluster.aws.dummy_aws_api import mock_aws_api


@pytest.mark.parametrize(
    "cluster_config_yaml, expected_warning_count, expected_warning_message",
    [
        # Test case 1: User explicitly sets SSH KeyName - should show warning
        (
            """
Region: us-east-1
Image:
  Os: alinux2
HeadNode:
  InstanceType: t3.micro
  Ssh:
    KeyName: head-node-key
  Networking:
    SubnetId: subnet-12345678
Scheduling:
  Scheduler: slurm
  SlurmQueues:
    - Name: queue1
      ComputeResources:
        - Name: compute1
          InstanceType: t3.micro
          MinCount: 0
          MaxCount: 10
      Networking:
        SubnetIds:
          - subnet-12345678
LoginNodes:
  Pools:
    - Name: pool1
      Count: 1
      InstanceType: t3.micro
      Ssh:
        KeyName: user-explicit-key  # User explicitly sets this
      Networking:
        SubnetIds:
          - subnet-12345678
""",
            1,
            "LoginNodes/Pools/Ssh/KeyName is deprecated since ParallelCluster version 3.14.0.",
        ),
        # Test case 2: User doesn't set SSH KeyName - should NOT show warning
        (
            """
Region: us-east-1
Image:
  Os: alinux2
HeadNode:
  InstanceType: t3.micro
  Ssh:
    KeyName: head-node-key
  Networking:
    SubnetId: subnet-12345678
Scheduling:
  Scheduler: slurm
  SlurmQueues:
    - Name: queue1
      ComputeResources:
        - Name: compute1
          InstanceType: t3.micro
          MinCount: 0
          MaxCount: 10
      Networking:
        SubnetIds:
          - subnet-12345678
LoginNodes:
  Pools:
    - Name: pool1
      Count: 1
      InstanceType: t3.micro
      # No SSH KeyName specified - will use head node key automatically
      Networking:
        SubnetIds:
          - subnet-12345678
""",
            0,
            None,
        ),
        # Test case 3: User sets other SSH settings but not KeyName - should NOT show warning
        (
            """
Region: us-east-1
Image:
  Os: alinux2
HeadNode:
  InstanceType: t3.micro
  Ssh:
    KeyName: head-node-key
  Networking:
    SubnetId: subnet-12345678
Scheduling:
  Scheduler: slurm
  SlurmQueues:
    - Name: queue1
      ComputeResources:
        - Name: compute1
          InstanceType: t3.micro
          MinCount: 0
          MaxCount: 10
      Networking:
        SubnetIds:
          - subnet-12345678
LoginNodes:
  Pools:
    - Name: pool1
      Count: 1
      InstanceType: t3.micro
      Ssh:
        AllowedIps: 10.0.0.0/16  # Only AllowedIps, no KeyName
      Networking:
        SubnetIds:
          - subnet-12345678
""",
            0,
            None,
        ),
    ],
)
def test_login_nodes_ssh_key_name_deprecation_integration(
    mocker, cluster_config_yaml, expected_warning_count, expected_warning_message
):
    mock_aws_api(mocker)
    mocker.patch("pcluster.utils.get_region", return_value="us-east-1")
    config_dict = yaml.safe_load(cluster_config_yaml)

    cluster_schema = ClusterSchema(cluster_name="test-cluster")
    cluster = cluster_schema.load(config_dict)
    validation_results = cluster.validate()

    # Filter for SSH key deprecation warnings
    ssh_warnings = [
        failure
        for failure in validation_results
        if "LoginNodes/Pools/Ssh/KeyName is deprecated" in failure.message and failure.level == FailureLevel.WARNING
    ]

    # Assert the expected number of warnings
    assert_that(len(ssh_warnings)).is_equal_to(expected_warning_count)

    # If we expect a warning, check the message content
    if expected_warning_count > 0 and expected_warning_message:
        assert_that(ssh_warnings[0].message).contains(expected_warning_message)

    # Verify that the SSH key is properly applied to login nodes
    if cluster.login_nodes and cluster.login_nodes.pools:
        for pool in cluster.login_nodes.pools:
            # SSH key should always be set (either explicitly or from head node)
            assert_that(pool.ssh.key_name).is_not_none()
            # If no warning, it should be the head node key
            if expected_warning_count == 0:
                assert_that(pool.ssh.key_name).is_equal_to(cluster.head_node.ssh.key_name)
