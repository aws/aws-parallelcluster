# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from assertpy import assert_that

from pcluster.config.cluster_config import QueueUpdateStrategy
from pcluster.config.config_patch import Change, ConfigPatch
from pcluster.config.update_policy import (
    UpdatePolicy,
    actions_needed_managed_fsx,
    condition_checker_managed_fsx,
    condition_checker_managed_placement_group,
    fail_reason_managed_fsx,
    fail_reason_managed_placement_group,
    is_managed_placement_group_deletion,
)
from pcluster.models.cluster import Cluster
from tests.pcluster.test_utils import dummy_cluster


@pytest.mark.parametrize(
    "is_fleet_stopped, key, path, old_value, new_value, update_strategy, other_changes, expected_result",
    [
        # tests with fleet stopped
        pytest.param(
            True,
            "SlurmQueues",
            ["Scheduling"],
            None,
            {
                "Name": "queue-added",
                "Networking": {"SubnetIds": "subnet-12345678"},
                "ComputeResources": {"Name": "compute-added", "InstanceType": "c5.9xlarge"},
            },
            None,
            [],
            True,
            id="stopped fleet and queue is added",
        ),
        pytest.param(
            True,
            "SlurmQueues",
            ["Scheduling"],
            {
                "Name": "queue-to-remove",
                "Networking": {"SubnetIds": "subnet-12345678"},
                "ComputeResources": {"Name": "compute-to-remove", "InstanceType": "c5.9xlarge"},
            },
            None,
            None,
            [],
            True,
            id="stopped fleet and queue is removed",
        ),
        pytest.param(
            True,
            "ComputeResources",
            ["Scheduling", "SlurmQueues[queue1]"],
            None,
            {"Name": "compute-added", "InstanceType": "c5.large", "MinCount": 1},
            None,
            [],
            True,
            id="stopped fleet and compute is added",
        ),
        pytest.param(
            True,
            "ComputeResources",
            ["Scheduling", "SlurmQueues[queue1]"],
            {"Name": "compute-to-remove", "InstanceType": "c5.large", "MinCount": 1},
            None,
            None,
            [],
            True,
            id="stopped fleet and compute is removed",
        ),
        pytest.param(
            True,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            10,
            0,
            None,
            [],
            True,
            id="stopped fleet and min count is decreased",
        ),
        pytest.param(
            True,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            0,
            10,
            None,
            [],
            True,
            id="stopped fleet and min count is increased",
        ),
        pytest.param(
            True,
            "MaxCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            10,
            0,
            None,
            [],
            True,
            id="stopped fleet and max count is decreased",
        ),
        pytest.param(
            True,
            "MaxCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            0,
            10,
            None,
            [],
            True,
            id="stopped fleet and max count is increased",
        ),
        # tests with fleet running
        pytest.param(
            False,
            "SlurmQueues",
            ["Scheduling"],
            None,
            {
                "Name": "queue-added",
                "Networking": {"SubnetIds": "subnet-12345678"},
                "ComputeResources": {"Name": "compute-added", "InstanceType": "c5.9xlarge"},
            },
            None,
            [],
            True,
            id="running fleet and queue is added",
        ),
        pytest.param(
            False,
            "SlurmQueues",
            ["Scheduling"],
            {
                "Name": "queue-to-remove",
                "Networking": {"SubnetIds": "subnet-12345678"},
                "ComputeResources": {"Name": "compute-to-remove", "InstanceType": "c5.9xlarge"},
            },
            None,
            None,
            [],
            False,
            id="running fleet and queue is removed wo update strategy",
        ),
        pytest.param(
            False,
            "SlurmQueues",
            ["Scheduling"],
            {
                "Name": "queue-to-remove",
                "Networking": {"SubnetIds": "subnet-12345678"},
                "ComputeResources": {"Name": "compute-to-remove", "InstanceType": "c5.9xlarge"},
            },
            None,
            QueueUpdateStrategy.TERMINATE.value,
            [],
            True,
            id="running fleet and queue is removed with TERMINATE update strategy",
        ),
        pytest.param(
            False,
            "SlurmQueues",
            ["Scheduling"],
            {
                "Name": "queue-to-remove",
                "Networking": {"SubnetIds": "subnet-12345678"},
                "ComputeResources": {"Name": "compute-to-remove", "InstanceType": "c5.9xlarge"},
            },
            None,
            QueueUpdateStrategy.DRAIN.value,
            [],
            False,
            id="running fleet and queue is removed with DRAIN update strategy",
        ),
        pytest.param(
            False,
            "ComputeResources",
            ["Scheduling", "SlurmQueues[queue1]"],
            None,
            {"Name": "compute-added", "InstanceType": "c5.large", "MinCount": 1},
            None,
            [],
            True,
            id="running fleet and compute is added",
        ),
        pytest.param(
            False,
            "ComputeResources",
            ["Scheduling", "SlurmQueues[queue1]"],
            {"Name": "compute-to-remove", "InstanceType": "c5.large", "MinCount": 1},
            None,
            None,
            [],
            False,
            id="running fleet and compute is removed wo update strategy",
        ),
        pytest.param(
            False,
            "ComputeResources",
            ["Scheduling", "SlurmQueues[queue1]"],
            {"Name": "compute-to-remove", "InstanceType": "c5.large", "MinCount": 1},
            None,
            QueueUpdateStrategy.TERMINATE.value,
            [],
            True,
            id="running fleet and compute is removed with TERMINATE update strategy",
        ),
        pytest.param(
            False,
            "ComputeResources",
            ["Scheduling", "SlurmQueues[queue1]"],
            {"Name": "compute-to-remove", "InstanceType": "c5.large", "MinCount": 1},
            None,
            QueueUpdateStrategy.DRAIN.value,
            [],
            False,
            id="running fleet and compute is removed with DRAIN update strategy",
        ),
        pytest.param(
            False,
            "MaxCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            10,
            0,
            None,
            [],
            False,
            id="running fleet and max count is decreased wo update strategy",
        ),
        pytest.param(
            False,
            "MaxCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            10,
            0,
            QueueUpdateStrategy.TERMINATE.value,
            [],
            True,
            id="running fleet and max count is decreased with TERMINATE update strategy",
        ),
        pytest.param(
            False,
            "MaxCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            10,
            0,
            QueueUpdateStrategy.DRAIN.value,
            [],
            False,
            id="running fleet and max count is decreased with DRAIN update strategy",
        ),
        pytest.param(
            False,
            "MaxCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            0,
            10,
            None,
            [],
            True,
            id="running fleet and max count is increased",
        ),
        pytest.param(
            False,
            "MaxCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            None,
            10,
            None,
            [],
            True,
            id="running fleet and max count is increased (initial value was not set)",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            10,
            0,
            None,
            [],
            False,
            id="running fleet and min count is decreased wo update strategy",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            10,
            0,
            QueueUpdateStrategy.TERMINATE.value,
            [],
            True,
            id="running fleet and  min count is decreased with TERMINATE update strategy",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            10,
            0,
            QueueUpdateStrategy.DRAIN.value,
            [],
            False,
            id="running fleet and  min count is decreased with DRAIN update strategy",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            0,
            10,
            None,
            [],
            False,
            id="running fleet and  min count is increased wo update strategy",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            0,
            10,
            QueueUpdateStrategy.TERMINATE.value,
            [],
            True,
            id="running fleet and min count is increased with TERMINATE update strategy",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            0,
            10,
            QueueUpdateStrategy.DRAIN.value,
            [],
            False,
            id="running fleet and  min count is increased with DRAIN update strategy",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            0,
            10,
            None,
            [
                Change(
                    path=["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
                    key="MaxCount",
                    old_value="0",
                    new_value="1",
                    update_policy={},
                    is_list=False,
                )
            ],
            False,
            id="running fleet and  min > max count are increased wo update strategy",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            0,
            10,
            None,
            [
                Change(
                    path=["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
                    key="MaxCount",
                    old_value=None,
                    new_value="1",
                    update_policy={},
                    is_list=False,
                )
            ],
            False,
            id="running fleet and  min > max count are increased wo update strategy (max count old value not set)",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            0,
            10,
            None,
            [
                Change(
                    path=["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
                    key="MaxCount",
                    old_value="0",
                    new_value="10",
                    update_policy={},
                    is_list=False,
                )
            ],
            True,
            id="running fleet and  min = max count are increased wo update strategy",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            None,
            10,
            None,
            [
                Change(
                    path=["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
                    key="MaxCount",
                    old_value=None,
                    new_value="10",
                    update_policy={},
                    is_list=False,
                )
            ],
            True,
            id="running fleet and  min = max count are increased wo update strategy "
            "(both min and max count old value not set)",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
            0,
            10,
            None,
            [
                Change(
                    path=["Scheduling", "SlurmQueues[queue1], ComputeResources[compute1]"],
                    key="MaxCount",
                    old_value="0",
                    new_value="20",
                    update_policy={},
                    is_list=False,
                )
            ],
            True,
            id="running fleet and  min < max count are increased wo update strategy",
        ),
    ],
)
def test_condition_checker_resize_update_strategy_on_remove(
    mocker, is_fleet_stopped, key, path, old_value, new_value, update_strategy, other_changes, expected_result
):
    cluster = dummy_cluster()
    cluster_has_running_capacity_mock = mocker.patch.object(
        cluster, "has_running_capacity", return_value=not is_fleet_stopped
    )

    patch_mock = mocker.MagicMock()
    patch_mock.cluster = cluster
    patch_mock.target_config = (
        {"Scheduling": {"SlurmSettings": {"QueueUpdateStrategy": update_strategy}}}
        if update_strategy
        else {"Scheduling": {"SlurmSettings": {}}}
    )
    if [other_changes]:
        patch_mock.changes = other_changes
    change_mock = mocker.MagicMock()
    change_mock.path = path
    change_mock.key = key
    change_mock.old_value = old_value
    change_mock.new_value = new_value

    assert_that(UpdatePolicy.RESIZE_UPDATE_STRATEGY_ON_REMOVE.condition_checker(change_mock, patch_mock)).is_equal_to(
        expected_result
    )
    assert_that(UpdatePolicy.RESIZE_UPDATE_STRATEGY_ON_REMOVE.fail_reason(change_mock, patch_mock)).is_equal_to(
        "All compute nodes must be stopped or QueueUpdateStrategy must be set to TERMINATE"
    )
    assert_that(UpdatePolicy.RESIZE_UPDATE_STRATEGY_ON_REMOVE.action_needed(change_mock, patch_mock)).is_equal_to(
        "Stop the compute fleet with the pcluster update-compute-fleet command, or set QueueUpdateStrategy to "
        "TERMINATE in the configuration used for the 'update-cluster' operation. Be aware that this update will remove "
        "nodes from the scheduler and terminates the EC2 instances associated. Jobs running on the removed nodes will "
        "terminate"
    )
    cluster_has_running_capacity_mock.assert_called()


@pytest.mark.parametrize(
    "is_fleet_stopped, key, path, old_value, new_value, update_strategy, expected_result",
    [
        pytest.param(
            True,
            "CustomAmi",
            ["Scheduling", "SlurmQueues[queue1]", "Image"],
            None,
            "ami-123456789",
            None,
            True,
            id="stopped fleet and custom AMI set",
        ),
        pytest.param(
            True,
            "CustomAmi",
            ["Scheduling", "SlurmQueues[queue1]", "Image"],
            "ami-123456789",
            None,
            None,
            True,
            id="stopped fleet and custom AMI unset",
        ),
        pytest.param(
            False,
            "CustomAmi",
            ["Scheduling", "SlurmQueues[queue1]", "Image"],
            None,
            "ami-123456789",
            None,
            False,
            id="running fleet and custom AMI set with no update strategy set",
        ),
        pytest.param(
            False,
            "CustomAmi",
            ["Scheduling", "SlurmQueues[queue1]", "Image"],
            "ami-987654321",
            "ami-123456789",
            None,
            False,
            id="running fleet and custom AMI change with no update strategy set",
        ),
        pytest.param(
            False,
            "CustomAmi",
            ["Scheduling", "SlurmQueues[queue1]", "Image"],
            "ami-987654321",
            "ami-123456789",
            QueueUpdateStrategy.COMPUTE_FLEET_STOP.value,
            False,
            id="running fleet and custom AMI change with update strategy COMPUTE_FLEET_STOP",
        ),
        pytest.param(
            False,
            "CustomAmi",
            ["Scheduling", "SlurmQueues[queue1]", "Image"],
            None,
            "ami-123456789",
            QueueUpdateStrategy.DRAIN.value,
            True,
            id="running fleet and custom AMI set with update strategy DRAIN",
        ),
        pytest.param(
            False,
            "CustomAmi",
            ["Scheduling", "SlurmQueues[queue1]", "Image"],
            "ami-123456789",
            None,
            QueueUpdateStrategy.DRAIN.value,
            True,
            id="running fleet and custom AMI unset with update strategy DRAIN",
        ),
        pytest.param(
            False,
            "GenerateSshKeysForUsers",
            ["DirectoryService"],
            None,
            True,
            QueueUpdateStrategy.DRAIN.value,
            False,
            id="running fleet with change outside SlurmQueues which requires COMPUTE_FLEET_STOP",
        ),
        pytest.param(
            False,
            "GenerateSshKeysForUsers",
            ["DirectoryService"],
            False,
            None,
            QueueUpdateStrategy.DRAIN.value,
            False,
            id="running fleet with change outside SlurmQueues which requires COMPUTE_FLEET_STOP",
        ),
        pytest.param(
            False,
            "GenerateSshKeysForUsers",
            ["DirectoryService"],
            True,
            False,
            QueueUpdateStrategy.DRAIN.value,
            False,
            id="running fleet with change outside SlurmQueues which requires COMPUTE_FLEET_STOP",
        ),
        pytest.param(
            False,
            "CustomAmi",
            ["Scheduling", "SlurmQueues[queue1]", "Image"],
            None,
            "ami-123456789",
            QueueUpdateStrategy.TERMINATE.value,
            True,
            id="running fleet and custom AMI set with update strategy TERMINATE",
        ),
        pytest.param(
            False,
            "CustomAmi",
            ["Scheduling", "SlurmQueues[queue1]", "Image"],
            "ami-123456789",
            None,
            QueueUpdateStrategy.TERMINATE.value,
            True,
            id="running fleet and custom AMI unset with update strategy TERMINATE",
        ),
        pytest.param(
            False,
            "GenerateSshKeysForUsers",
            ["DirectoryService"],
            None,
            True,
            QueueUpdateStrategy.TERMINATE.value,
            False,
            id="running fleet with change outside SlurmQueues which requires COMPUTE_FLEET_STOP",
        ),
        pytest.param(
            False,
            "GenerateSshKeysForUsers",
            ["DirectoryService"],
            False,
            None,
            QueueUpdateStrategy.TERMINATE.value,
            False,
            id="running fleet with change outside SlurmQueues which requires COMPUTE_FLEET_STOP",
        ),
        pytest.param(
            False,
            "GenerateSshKeysForUsers",
            ["DirectoryService"],
            True,
            False,
            QueueUpdateStrategy.TERMINATE.value,
            False,
            id="running fleet with change outside SlurmQueues which requires COMPUTE_FLEET_STOP",
        ),
        pytest.param(
            False,
            "Tags",
            ["Scheduling", "SlurmQueues[queue1]"],
            '{"Key": "queue_tag1","Value": "queue_tag_value_1"}',
            None,
            QueueUpdateStrategy.DRAIN.value,
            True,
            id="running fleet and queue tag unset with update strategy DRAIN",
        ),
        pytest.param(
            False,
            "Tags",
            ["Scheduling", "SlurmQueues[queue1]"],
            None,
            '{"Key": "queue_tag1","Value": "queue_tag_value_1"}',
            None,
            False,
            id="running fleet and queue tag set without queue update strategy",
        ),
        pytest.param(
            False,
            "Value",
            ["Scheduling", "SlurmQueues[queue1]", "Tags[tag1]"],
            "value_1",
            "value_2",
            QueueUpdateStrategy.DRAIN.value,
            True,
            id="running fleet and change queue tag with update strategy DRAIN",
        ),
        pytest.param(
            True,
            "Value2",
            ["Scheduling", "SlurmQueues[queue1]", "Tags[tag1]"],
            "value_1",
            "value_2",
            None,
            True,
            id="Stop fleet and queue tag unset without queue update strategy",
        ),
        pytest.param(
            False,
            "Tags",
            ["Scheduling", "SlurmQueues[queue1]", "ComputeResources", "Tags[computetag1]"],
            '{"Key": "compute_tag2","Value": "compute_tag_value_1"}',
            None,
            QueueUpdateStrategy.DRAIN.value,
            True,
            id="running fleet and compute tag unset with update strategy DRAIN",
        ),
        pytest.param(
            False,
            "Value",
            ["Scheduling", "SlurmQueues[queue1]", "ComputeResources[compute-resource1]", "Tags[computetag1]"],
            "value_1",
            "value_2",
            None,
            False,
            id="running fleet and change compute tag without update strategy DRAIN",
        ),
    ],
)
def test_queue_update_strategy_condition_checker(
    mocker, is_fleet_stopped, key, path, old_value, new_value, update_strategy, expected_result
):
    cluster = dummy_cluster()
    cluster_has_running_capacity_mock = mocker.patch.object(
        cluster, "has_running_capacity", return_value=not is_fleet_stopped
    )

    patch_mock = mocker.MagicMock()
    patch_mock.cluster = cluster
    patch_mock.target_config = (
        {"Scheduling": {"SlurmSettings": {"QueueUpdateStrategy": update_strategy}}}
        if update_strategy
        else {"Scheduling": {"SlurmSettings": {}}}
    )
    change_mock = mocker.MagicMock()
    change_mock.path = path
    change_mock.key = key
    change_mock.old_value = old_value
    change_mock.new_value = new_value

    assert_that(UpdatePolicy.QUEUE_UPDATE_STRATEGY.condition_checker(change_mock, patch_mock)).is_equal_to(
        expected_result
    )
    cluster_has_running_capacity_mock.assert_called()


@pytest.mark.parametrize(
    "is_fleet_stopped, key, path, old_value, new_value, expected_result",
    [
        pytest.param(
            True,
            "Instances",
            ["Scheduling", "SlurmQueues[queue1]", "ComputeResources[compute-resource1]"],
            None,
            {"InstanceType": "c5.9xlarge"},
            True,
            id="stopped fleet and instance type is added",
        ),
        pytest.param(
            True,
            "Instances",
            ["Scheduling", "SlurmQueues[queue1]", "ComputeResources[compute-resource1]"],
            {"InstanceType": "c5.9xlarge"},
            None,
            True,
            id="stopped fleet and instance type is removed",
        ),
        pytest.param(
            False,
            "Instances",
            ["Scheduling", "SlurmQueues[queue1]", "ComputeResources[compute-resource1]"],
            None,
            {"InstanceType": "c5.9xlarge"},
            True,
            id="running fleet and instance type is added",
        ),
        pytest.param(
            False,
            "Instances",
            ["Scheduling", "SlurmQueues[queue1]", "ComputeResources[compute-resource1]"],
            {"InstanceType": "c5.9xlarge"},
            None,
            False,
            id="running fleet and instance type is removed",
        ),
    ],
)
def test_condition_checker_compute_fleet_stop_on_remove(
    mocker, is_fleet_stopped, key, path, old_value, new_value, expected_result
):
    cluster = dummy_cluster()
    cluster_has_running_capacity_mock = mocker.patch.object(
        cluster, "has_running_capacity", return_value=not is_fleet_stopped
    )

    patch_mock = mocker.MagicMock()
    patch_mock.cluster = cluster

    change_mock = mocker.MagicMock()
    change_mock.path = path
    change_mock.key = key
    change_mock.old_value = old_value
    change_mock.new_value = new_value

    assert_that(UpdatePolicy.COMPUTE_FLEET_STOP_ON_REMOVE.condition_checker(change_mock, patch_mock)).is_equal_to(
        expected_result
    )
    cluster_has_running_capacity_mock.assert_called()


@pytest.mark.parametrize(
    "key, path, old_value, new_value, expected_fail_reason, expected_actions_needed",
    [
        pytest.param(
            "CustomAmi",
            ["Scheduling", "SlurmQueues[queue6]", "Image"],
            None,
            "ami-123456789",
            "All compute nodes must be stopped or QueueUpdateStrategy must be set",
            "Stop the compute fleet with the pcluster update-compute-fleet command, "
            "or set QueueUpdateStrategy in the configuration used for the 'update-cluster' operation",
            id="change within SlurmQueues",
        ),
    ],
)
def test_queue_update_strategy_fail_reason_and_actions_needed(
    mocker, key, path, old_value, new_value, expected_fail_reason, expected_actions_needed
):
    cluster = dummy_cluster()
    patch_mock = mocker.MagicMock()
    patch_mock.cluster = cluster
    change_mock = mocker.MagicMock()
    change_mock.path = path
    change_mock.key = key
    change_mock.old_value = old_value
    change_mock.new_value = new_value

    assert_that(UpdatePolicy.QUEUE_UPDATE_STRATEGY.fail_reason(change_mock, patch_mock)).is_equal_to(
        expected_fail_reason
    )
    assert_that(UpdatePolicy.QUEUE_UPDATE_STRATEGY.action_needed(change_mock, patch_mock)).is_equal_to(
        expected_actions_needed
    )


@pytest.mark.parametrize(
    "key, path, old_value, new_value, expected_fail_reason, expected_actions_needed",
    [
        pytest.param(
            "SlurmQueues",
            ["Scheduling"],
            {
                "Name": "queue-to-remove",
                "Networking": {"SubnetIds": "subnet-12345678"},
                "ComputeResources": {"Name": "compute-to-remove", "InstanceType": "c5.9xlarge"},
            },
            None,
            "All compute nodes must be stopped",
            "Stop the compute fleet with the pcluster update-compute-fleet command",
            id="remove a Slurm queue",
        ),
    ],
)
def test_compute_fleet_stop_on_remove_fail_reason_and_actions_needed(
    mocker, key, path, old_value, new_value, expected_fail_reason, expected_actions_needed
):
    cluster = dummy_cluster()
    patch_mock = mocker.MagicMock()
    patch_mock.cluster = cluster
    change_mock = mocker.MagicMock()
    change_mock.path = path
    change_mock.key = key
    change_mock.old_value = old_value
    change_mock.new_value = new_value

    assert_that(UpdatePolicy.COMPUTE_FLEET_STOP_ON_REMOVE.fail_reason).is_equal_to(expected_fail_reason)
    assert_that(UpdatePolicy.COMPUTE_FLEET_STOP_ON_REMOVE.action_needed(change_mock, patch_mock)).is_equal_to(
        expected_actions_needed
    )


@pytest.mark.parametrize(
    "key, path, old_value, new_value, expected_fail_reason, expected_actions_needed",
    [
        pytest.param(
            "MinCount",
            ["Scheduling", "SlurmQueues[queue6]", "ComputeResources[compute6]"],
            0,
            None,
            "All compute nodes must be stopped",
            "Stop the compute fleet with the pcluster update-compute-fleet command",
            id="change within SlurmQueues",
        ),
        pytest.param(
            "GenerateSshKeysForUsers",
            ["DirectoryService"],
            None,
            True,
            "All compute nodes must be stopped",
            "Stop the compute fleet with the pcluster update-compute-fleet command",
            id="change outside SlurmQueues",
        ),
    ],
)
def test_compute_fleet_stop_fail_reason_and_actions_needed(
    mocker, key, path, old_value, new_value, expected_fail_reason, expected_actions_needed
):
    cluster = dummy_cluster()
    patch_mock = mocker.MagicMock()
    patch_mock.cluster = cluster
    change_mock = mocker.MagicMock()
    change_mock.path = path
    change_mock.key = key
    change_mock.old_value = old_value
    change_mock.new_value = new_value

    assert_that(UpdatePolicy.COMPUTE_FLEET_STOP.fail_reason).is_equal_to(expected_fail_reason)
    assert_that(UpdatePolicy.COMPUTE_FLEET_STOP.action_needed(change_mock, patch_mock)).is_equal_to(
        expected_actions_needed
    )


managed_ebs = {
    "MountDir": "/ebs-managed",
    "Name": "ebs-managed",
    "StorageType": "Ebs",
}

managed_efs = {
    "MountDir": "/efs-managed",
    "Name": "efs-managed",
    "StorageType": "Efs",
}

external_efs = {
    "MountDir": "/efs-external",
    "Name": "efs-external",
    "StorageType": "Efs",
    "EfsSettings": {"FileSystemId": "fs-123456789"},
}

managed_fsx_lustre = {
    "MountDir": "/fsx-managed",
    "Name": "fsx-managed",
    "StorageType": "FsxLustre",
}

external_fsx_lustre = {
    "MountDir": "/fsx-external",
    "Name": "fsx-external",
    "StorageType": "FsxLustre",
    "FsxLustreSettings": {"FileSystemId": "fs-123456789"},
}


@pytest.mark.parametrize(
    "is_fleet_stopped, has_running_login_nodes, key, path, old_value, new_value, update_strategy, expected_result, "
    "expected_fail_reason, expected_actions_needed, scheduler",
    [
        # Managed EBS
        pytest.param(
            True,
            False,
            "SharedStorage",
            [],
            None,
            managed_ebs,
            None,
            True,
            None,
            None,
            "slurm",
            id="Compute stopped, login stopped, add managed EBS, update strategy not set: accepted",
        ),
        pytest.param(
            True,
            False,
            "SharedStorage",
            [],
            managed_ebs,
            None,
            None,
            True,
            None,
            None,
            "slurm",
            id="Compute stopped, login stopped, remove managed EBS, update strategy not set: accepted",
        ),
        pytest.param(
            False,
            False,
            "SharedStorage",
            [],
            None,
            managed_ebs,
            None,
            False,
            "All compute nodes must be stopped or QueueUpdateStrategy must be set.",
            "Stop the compute fleet with the pcluster update-compute-fleet command, or set QueueUpdateStrategy in the "
            "configuration used for the 'update-cluster' operation.",
            "slurm",
            id="Compute running, login stopped, add managed EBS, update strategy not set: rejected",
        ),
        pytest.param(
            False,
            True,
            "SharedStorage",
            [],
            None,
            managed_ebs,
            None,
            False,
            "Update actions are not currently supported for the 'SharedStorage' parameter",
            "Restore the parameter 'SharedStorage'. If you need this change, please consider creating a new cluster "
            "instead of updating the existing one.",
            "awsbatch",
            id="Compute running, login running, add managed EBS, update strategy not set, with awsbatch: rejected",
        ),
        pytest.param(
            False,
            False,
            "SharedStorage",
            [],
            None,
            managed_ebs,
            QueueUpdateStrategy.TERMINATE.value,
            True,
            None,
            None,
            "slurm",
            id="Compute running, login stopped, add managed EBS, update strategy TERMINATE: accepted",
        ),
        pytest.param(
            False,
            False,
            "SharedStorage",
            [],
            managed_ebs,
            None,
            QueueUpdateStrategy.DRAIN.value,
            True,
            None,
            None,
            "slurm",
            id="Compute running, login stopped, remove managed EBS, update strategy DRAIN: accepted",
        ),
        # Managed EFS
        pytest.param(
            False,
            False,
            "SharedStorage",
            [],
            None,
            managed_efs,
            QueueUpdateStrategy.TERMINATE.value,
            True,
            None,
            None,
            "slurm",
            id="Compute running, login stopped, add managed EFS, update strategy TERMINATE: accepted",
        ),
        pytest.param(
            True,
            False,
            "SharedStorage",
            [],
            managed_efs,
            None,
            None,
            True,
            None,
            None,
            "slurm",
            id="Compute stopped, login stopped, remove managed EFS, update strategy not set: accepted",
        ),
        pytest.param(
            False,
            True,
            "SharedStorage",
            [],
            managed_efs,
            None,
            QueueUpdateStrategy.DRAIN.value,
            False,
            "All login nodes must be stopped.",
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute running, login running, remove managed EFS, update strategy DRAIN: rejected",
        ),
        pytest.param(
            False,
            True,
            "SharedStorage",
            [],
            managed_efs,
            None,
            None,
            False,
            "All compute nodes must be stopped or QueueUpdateStrategy must be set. All login nodes must be stopped.",
            "Stop the compute fleet with the pcluster update-compute-fleet command, "
            "or set QueueUpdateStrategy in the configuration used for the 'update-cluster' operation. "
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute running, login running, remove managed EFS, update strategy not set: rejected",
        ),
        pytest.param(
            False,
            True,
            "SharedStorage",
            [],
            managed_efs,
            None,
            None,
            False,
            "Update actions are not currently supported for the 'SharedStorage' parameter",
            "Restore 'SharedStorage' value to "
            "'{'MountDir': '/efs-managed', 'Name': 'efs-managed', 'StorageType': 'Efs'}'",
            "awsbatch",
            id="Compute running, login running, remove managed EFS, update strategy not set: rejected",
        ),
        pytest.param(
            False,
            True,
            "SharedStorage",
            [],
            managed_efs,
            None,
            QueueUpdateStrategy.DRAIN.value,
            False,
            "All login nodes must be stopped.",
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute running, login running, remove managed EFS, update strategy DRAIN: rejected",
        ),
        # External EFS
        pytest.param(
            True,
            False,
            "SharedStorage",
            [],
            None,
            external_efs,
            None,
            True,
            None,
            None,
            "slurm",
            id="Compute stopped, login stopped, add external EFS, no update strategy set: accepted",
        ),
        pytest.param(
            True,
            False,
            "SharedStorage",
            [],
            external_efs,
            None,
            None,
            True,
            None,
            None,
            "slurm",
            id="Compute stopped, login stopped, remove external EFS, no update strategy set: accepted",
        ),
        pytest.param(
            False,
            True,
            "SharedStorage",
            [],
            None,
            external_efs,
            None,
            False,
            "All login nodes must be stopped.",
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute running, login running, add external EFS, update strategy not set: rejected",
        ),
        pytest.param(
            False,
            True,
            "SharedStorage",
            [],
            external_efs,
            None,
            None,
            False,
            "All login nodes must be stopped.",
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute running, login running, remove external EFS, update strategy not set: rejected",
        ),
        pytest.param(
            True,
            True,
            "SharedStorage",
            [],
            None,
            external_efs,
            None,
            False,
            "All login nodes must be stopped.",
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute stopped, login running, add external EFS, update strategy not set: rejected",
        ),
        pytest.param(
            True,
            True,
            "SharedStorage",
            [],
            external_efs,
            None,
            None,
            False,
            "All login nodes must be stopped.",
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute stopped, login running, remove external EFS, update strategy not set: rejected",
        ),
        pytest.param(
            False,
            False,
            "SharedStorage",
            [],
            None,
            external_efs,
            None,
            True,
            None,
            None,
            "slurm",
            id="Compute running, login stopped, add external EFS, update strategy not set: accepted",
        ),
        pytest.param(
            False,
            False,
            "SharedStorage",
            [],
            external_efs,
            None,
            None,
            True,
            None,
            None,
            "slurm",
            id="Compute running, login stopped, remove external EFS, update strategy not set: accepted",
        ),
        # Managed FSxLustre
        pytest.param(
            True,
            False,
            "SharedStorage",
            [],
            None,
            managed_fsx_lustre,
            None,
            True,
            None,
            None,
            "slurm",
            id="Compute stopped, login stopped, add managed FSxLustre, update strategy not set: accepted",
        ),
        pytest.param(
            True,
            False,
            "SharedStorage",
            [],
            managed_fsx_lustre,
            None,
            None,
            True,
            None,
            None,
            "slurm",
            id="Compute stopped, login stopped, remove managed FSxLustre, no update strategy set: accepted",
        ),
        pytest.param(
            False,
            True,
            "SharedStorage",
            [],
            None,
            managed_fsx_lustre,
            None,
            False,
            "All compute nodes must be stopped or QueueUpdateStrategy must be set. All login nodes must be stopped.",
            "Stop the compute fleet with the pcluster update-compute-fleet command, "
            "or set QueueUpdateStrategy in the configuration used for the 'update-cluster' operation. "
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute running, login running, add managed FSxLustre, update strategy not set: rejected",
        ),
        pytest.param(
            False,
            True,
            "SharedStorage",
            [],
            managed_fsx_lustre,
            None,
            None,
            False,
            "All compute nodes must be stopped or QueueUpdateStrategy must be set. All login nodes must be stopped.",
            "Stop the compute fleet with the pcluster update-compute-fleet command, "
            "or set QueueUpdateStrategy in the configuration used for the 'update-cluster' operation. "
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute running, login running, remove managed FSxLustre, update strategy not set: rejected",
        ),
        pytest.param(
            True,
            True,
            "SharedStorage",
            [],
            None,
            managed_fsx_lustre,
            None,
            False,
            "All login nodes must be stopped.",
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute stopped, login running, add managed FSxLustre, update strategy not set: rejected",
        ),
        pytest.param(
            True,
            True,
            "SharedStorage",
            [],
            managed_fsx_lustre,
            None,
            None,
            False,
            "All login nodes must be stopped.",
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute stopped, login running, remove managed FSxLustre, update strategy not set: rejected",
        ),
        pytest.param(
            False,
            True,
            "SharedStorage",
            [],
            managed_fsx_lustre,
            None,
            QueueUpdateStrategy.DRAIN.value,
            False,
            "All login nodes must be stopped.",
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute running, login running, remove managed FSxLustre, update strategy DRAIN: rejected",
        ),
        pytest.param(
            False,
            False,
            "SharedStorage",
            [],
            None,
            managed_fsx_lustre,
            None,
            False,
            "All compute nodes must be stopped or QueueUpdateStrategy must be set.",
            "Stop the compute fleet with the pcluster update-compute-fleet command, "
            "or set QueueUpdateStrategy in the configuration used for the 'update-cluster' operation.",
            "slurm",
            id="Compute running, login stopped, add managed FSxLustre, update strategy not set: rejected",
        ),
        pytest.param(
            False,
            False,
            "SharedStorage",
            [],
            managed_fsx_lustre,
            None,
            None,
            False,
            "All compute nodes must be stopped or QueueUpdateStrategy must be set.",
            "Stop the compute fleet with the pcluster update-compute-fleet command, "
            "or set QueueUpdateStrategy in the configuration used for the 'update-cluster' operation.",
            "slurm",
            id="Compute running, login stopped, remove managed FSxLustre, update strategy not set: rejected",
        ),
        pytest.param(
            False,
            False,
            "SharedStorage",
            [],
            None,
            {"MountDir": "/fsx", "Name": "fsx", "StorageType": "FsxLustre"},
            QueueUpdateStrategy.TERMINATE.value,
            True,
            None,
            None,
            "slurm",
            id="Compute running, login stopped, add managed FSxLustre, update strategy TERMINATE: accepted",
        ),
        # External FSx
        # We test FSxLustre, as an FSx storage to cover all the other FSx storage types (Ontap, OpenZfs, FileCache)
        pytest.param(
            True,
            False,
            "SharedStorage",
            [],
            None,
            external_fsx_lustre,
            None,
            True,
            None,
            None,
            "slurm",
            id="Compute stopped, login stopped, add external FSxLustre, no update strategy set: accepted",
        ),
        pytest.param(
            True,
            False,
            "SharedStorage",
            [],
            external_fsx_lustre,
            None,
            None,
            True,
            None,
            None,
            "slurm",
            id="Compute stopped, login stopped, remove external FSxLustre, no update strategy set: accepted",
        ),
        pytest.param(
            False,
            True,
            "SharedStorage",
            [],
            None,
            external_fsx_lustre,
            None,
            False,
            "All login nodes must be stopped.",
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute running, login running, add external FSxLustre, update strategy not set: rejected",
        ),
        pytest.param(
            False,
            True,
            "SharedStorage",
            [],
            external_fsx_lustre,
            None,
            None,
            False,
            "All login nodes must be stopped.",
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute running, login running, remove external FSxLustre, update strategy not set: rejected",
        ),
        pytest.param(
            True,
            True,
            "SharedStorage",
            [],
            None,
            external_fsx_lustre,
            None,
            False,
            "All login nodes must be stopped.",
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute stopped, login running, add external FSxLustre, update strategy not set: rejected",
        ),
        pytest.param(
            True,
            True,
            "SharedStorage",
            [],
            external_fsx_lustre,
            None,
            None,
            False,
            "All login nodes must be stopped.",
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            "slurm",
            id="Compute stopped, login running, remove external FSxLustre, update strategy not set: rejected",
        ),
        pytest.param(
            False,
            False,
            "SharedStorage",
            [],
            None,
            external_fsx_lustre,
            None,
            True,
            None,
            None,
            "slurm",
            id="Compute running, login stopped, add external FSxLustre, update strategy not set: accepted",
        ),
        pytest.param(
            False,
            False,
            "SharedStorage",
            [],
            external_fsx_lustre,
            None,
            None,
            True,
            None,
            None,
            "slurm",
            id="Compute running, login stopped, remove external FSxLustre, update strategy not set: accepted",
        ),
    ],
)
def test_shared_storage_update_policy_condition_checker(
    mocker,
    is_fleet_stopped,
    has_running_login_nodes,
    key,
    path,
    old_value,
    new_value,
    update_strategy,
    expected_result,
    expected_fail_reason,
    expected_actions_needed,
    scheduler,
):
    cluster = dummy_cluster()
    cluster_has_running_capacity_mock = mocker.patch.object(
        cluster, "has_running_capacity", return_value=not is_fleet_stopped
    )
    cluster_has_running_login_nodes_mock = mocker.patch.object(
        cluster, "has_running_login_nodes", return_value=has_running_login_nodes
    )
    mocker.patch(
        "pcluster.config.update_policy.is_awsbatch_scheduler", return_value=True if scheduler == "awsbatch" else False
    )
    mocker.patch(
        "pcluster.config.update_policy.is_slurm_scheduler", return_value=True if scheduler == "slurm" else False
    )
    patch_mock = mocker.MagicMock()
    patch_mock.cluster = cluster
    if scheduler == "slurm":
        patch_mock.target_config = (
            {"Scheduling": {"SlurmSettings": {"QueueUpdateStrategy": update_strategy}}}
            if update_strategy
            else {"Scheduling": {"SlurmSettings": {}}}
        )
    else:
        patch_mock.target_config = {"Scheduling": {}}

    change_mock = mocker.MagicMock()
    change_mock.path = path
    change_mock.key = key
    change_mock.old_value = old_value
    change_mock.new_value = new_value

    assert_that(UpdatePolicy.SHARED_STORAGE_UPDATE_POLICY.condition_checker(change_mock, patch_mock)).is_equal_to(
        expected_result
    )
    if not expected_result:
        assert_that(UpdatePolicy.SHARED_STORAGE_UPDATE_POLICY.fail_reason(change_mock, patch_mock)).is_equal_to(
            expected_fail_reason
        )
        assert_that(UpdatePolicy.SHARED_STORAGE_UPDATE_POLICY.action_needed(change_mock, patch_mock)).is_equal_to(
            expected_actions_needed
        )
    if scheduler != "awsbatch":
        cluster_has_running_login_nodes_mock.assert_called()
        cluster_has_running_capacity_mock.assert_called()
    else:
        cluster_has_running_login_nodes_mock.assert_not_called()


@pytest.mark.parametrize(
    "base_config, target_config, change, has_running_capacity, "
    "expected_result_pg, expected_result_top, expected_message",
    [
        # Positive test case, no placement group before or after
        pytest.param(
            {"Scheduling": {"Queues": [{"Name": "mock-q"}]}},
            {"Scheduling": {"Queues": [{"Name": "mock-q"}]}},
            Change(path=["Queues[mock-q]"], key="", old_value="", new_value="", update_policy={}, is_list=False),
            False,
            False,
            True,
            "All compute nodes must be stopped",
        ),
        # Positive test case, create a placement group at the queue level
        pytest.param(
            {"Scheduling": {"Queues": [{"Name": "mock-q"}]}},
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "Networking": {
                                "SubnetIds": ["subnet-0bfcd29fad2404485"],
                                "PlacementGroup": {"Enabled": True},
                            },
                        }
                    ]
                }
            },
            Change(path=["Queues[mock-q]"], key="", old_value="", new_value="", update_policy={}, is_list=False),
            False,
            False,
            True,
            "All compute nodes must be stopped",
        ),
        # Positive test case, create a placement group at the compute resource level
        pytest.param(
            {"Scheduling": {"Queues": [{"Name": "mock-q"}]}},
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled",
                                    "Networking": {"PlacementGroup": {"Enabled": True}},
                                }
                            ],
                        }
                    ]
                }
            },
            Change(path=["Queues[mock-q]"], key="", old_value="", new_value="", update_policy={}, is_list=False),
            False,
            False,
            True,
            "All compute nodes must be stopped",
        ),
        # Positive test case, enable pg at compute resource level, while disabled at q level
        pytest.param(
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "Networking": {"PlacementGroup": {"Enabled": False}},
                            "ComputeResources": [
                                {"Name": "cr-pg-enabled", "Networking": {"PlacementGroup": {"Enabled": False}}}
                            ],
                        }
                    ]
                }
            },
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "Networking": {"PlacementGroup": {"Enabled": False}},
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled",
                                    "Networking": {"PlacementGroup": {"Enabled": True}},
                                }
                            ],
                        }
                    ]
                }
            },
            Change(path=["Queues[mock-q]"], key="", old_value="", new_value="", update_policy={}, is_list=False),
            False,
            False,
            True,
            "All compute nodes must be stopped",
        ),
        # Positive test case, enable pg at compute resource level with a name
        pytest.param(
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "Networking": {"PlacementGroup": {"Enabled": False}},
                            "ComputeResources": [
                                {"Name": "cr-pg-enabled", "Networking": {"PlacementGroup": {"Enabled": False}}}
                            ],
                        }
                    ]
                }
            },
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "Networking": {"PlacementGroup": {"Enabled": False}},
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled",
                                    "Networking": {"PlacementGroup": {"Enabled": True, "Name": "mock-name"}},
                                }
                            ],
                        }
                    ]
                }
            },
            Change(path=["Queues[mock-q]"], key="", old_value="", new_value="", update_policy={}, is_list=False),
            False,
            False,
            True,
            "All compute nodes must be stopped",
        ),
        # Positive test case, disable named pg at compute resource level
        pytest.param(
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "Networking": {"PlacementGroup": {"Enabled": False}},
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled",
                                    "Networking": {"PlacementGroup": {"Enabled": True, "Name": "mock-name"}},
                                }
                            ],
                        }
                    ]
                }
            },
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "Networking": {"PlacementGroup": {"Enabled": False}},
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled",
                                    "Networking": {"PlacementGroup": {"Enabled": False}},
                                }
                            ],
                        }
                    ]
                }
            },
            Change(path=["Queues[mock-q]"], key="", old_value="", new_value="", update_policy={}, is_list=False),
            False,
            False,
            True,
            "All compute nodes must be stopped",
        ),
        # Negative test case, enable pg at compute resource level, while removing from the
        # queue level and testing the change at the queue level
        pytest.param(
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "Networking": {"PlacementGroup": {"Enabled": True}},
                            "ComputeResources": [{"Name": "cr-pg-enabled"}],
                        }
                    ]
                }
            },
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled",
                                    "Networking": {"PlacementGroup": {"Enabled": True}},
                                }
                            ],
                        }
                    ]
                }
            },
            Change(path=["Queues[mock-q]"], key="", old_value="", new_value="", update_policy={}, is_list=False),
            True,
            True,
            False,
            "All compute nodes must be stopped for a managed placement group deletion",
        ),
        # Positive test case, disable at the q level with no running capacity
        pytest.param(
            {"Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"PlacementGroup": {"Enabled": True}}}]}},
            {"Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"PlacementGroup": {"Enabled": False}}}]}},
            Change(path=["Queues[mock-q]"], key="", old_value="", new_value="", update_policy={}, is_list=False),
            False,
            True,
            True,
            "All compute nodes must be stopped for a managed placement group deletion",
        ),
        # Negative test case, disable at the q level
        pytest.param(
            {"Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"PlacementGroup": {"Enabled": True}}}]}},
            {"Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"PlacementGroup": {"Enabled": False}}}]}},
            Change(path=["Queues[mock-q]"], key="", old_value="", new_value="", update_policy={}, is_list=False),
            True,
            True,
            False,
            "All compute nodes must be stopped for a managed placement group deletion",
        ),
        # Positive test case, disable named pg at the q level
        pytest.param(
            {
                "Scheduling": {
                    "Queues": [{"Name": "mock-q", "Networking": {"PlacementGroup": {"Enabled": True, "Id": "mock-id"}}}]
                }
            },
            {"Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"PlacementGroup": {"Enabled": False}}}]}},
            Change(path=["Queues[mock-q]"], key="", old_value="", new_value="", update_policy={}, is_list=False),
            False,
            False,
            True,
            "All compute nodes must be stopped",
        ),
        # Negative test case, disable at the q level by omission
        pytest.param(
            {"Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"PlacementGroup": {"Enabled": True}}}]}},
            {"Scheduling": {"Queues": [{"Name": "mock-q"}]}},
            Change(path=["Queues[mock-q]"], key="", old_value="", new_value="", update_policy={}, is_list=False),
            True,
            True,
            False,
            "All compute nodes must be stopped for a managed placement group deletion",
        ),
        # Negative test case, disable at the cr level
        pytest.param(
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled",
                                    "Networking": {"PlacementGroup": {"Enabled": True}},
                                }
                            ],
                        }
                    ]
                }
            },
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled",
                                    "Networking": {"PlacementGroup": {"Enabled": False}},
                                }
                            ],
                        }
                    ]
                }
            },
            Change(
                path=["Queues[mock-q]", "ComputeResources[cr-pg-enabled]"],
                key="",
                old_value="",
                new_value="",
                update_policy={},
                is_list=False,
            ),
            True,
            True,
            False,
            "All compute nodes must be stopped for a managed placement group deletion",
        ),
        # Negative test case, disable at the cr level by omission
        pytest.param(
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled",
                                    "Networking": {"PlacementGroup": {"Enabled": True}},
                                }
                            ],
                            "Networking": {"PlacementGroup": {"Enabled": True}},
                        }
                    ]
                }
            },
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled",
                                    "Networking": {"PlacementGroup": {"Enabled": False}},
                                }
                            ],
                            "Networking": {"PlacementGroup": {"Enabled": True}},
                        }
                    ]
                }
            },
            Change(
                path=["Queues[mock-q]", "ComputeResources[cr-pg-enabled]"],
                key="",
                old_value="",
                new_value="",
                update_policy={},
                is_list=False,
            ),
            True,
            True,
            False,
            "All compute nodes must be stopped for a managed placement group deletion",
        ),
        # Negative test case, disable at the cr level, while enabled at q
        pytest.param(
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "Networking": {"PlacementGroup": {"Enabled": True}},
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled",
                                    "Networking": {"PlacementGroup": {"Enabled": True}},
                                }
                            ],
                        }
                    ]
                }
            },
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "Networking": {"PlacementGroup": {"Enabled": True}},
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled",
                                    "Networking": {"PlacementGroup": {"Enabled": False}},
                                }
                            ],
                        }
                    ]
                }
            },
            Change(
                path=["Queues[mock-q]", "ComputeResources[cr-pg-enabled]"],
                key="",
                old_value="",
                new_value="",
                update_policy={},
                is_list=False,
            ),
            True,
            True,
            False,
            "All compute nodes must be stopped for a managed placement group deletion",
        ),
        # Negative test case, disable at the cr level, while enabled at q, multiple queues
        pytest.param(
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "Networking": {"PlacementGroup": {"Enabled": True}},
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled",
                                    "Networking": {"PlacementGroup": {"Enabled": True}},
                                }
                            ],
                        },
                        {
                            "Name": "mock-q-2",
                            "Networking": {"PlacementGroup": {"Enabled": True}},
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled-2",
                                    "Networking": {"PlacementGroup": {"Enabled": True}},
                                }
                            ],
                        },
                    ]
                }
            },
            {
                "Scheduling": {
                    "Queues": [
                        {
                            "Name": "mock-q",
                            "Networking": {"PlacementGroup": {"Enabled": True}},
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled",
                                }
                            ],
                        },
                        {
                            "Name": "mock-q-2",
                            "Networking": {"PlacementGroup": {"Enabled": True}},
                            "ComputeResources": [
                                {
                                    "Name": "cr-pg-enabled-2",
                                    "Networking": {"PlacementGroup": {"Enabled": False}},
                                }
                            ],
                        },
                    ]
                }
            },
            Change(
                path=["Queues[mock-q-2]", "ComputeResources[cr-pg-enabled-2]"],
                key="",
                old_value="",
                new_value="",
                update_policy={},
                is_list=False,
            ),
            True,
            True,
            False,
            "All compute nodes must be stopped for a managed placement group deletion",
        ),
    ],
)
def test_condition_checker_managed_placement_group(
    mocker,
    base_config,
    target_config,
    change,
    has_running_capacity,
    expected_result_pg,
    expected_result_top,
    expected_message,
):
    cluster = Cluster(name="mock-name", stack="mock-stack")
    mocker.patch.object(cluster, "has_running_capacity", return_value=has_running_capacity)
    patch = ConfigPatch(cluster=cluster, base_config=base_config, target_config=target_config)
    actual_pg = is_managed_placement_group_deletion(change, patch)
    assert_that(actual_pg).is_equal_to(expected_result_pg)
    actual_top = condition_checker_managed_placement_group(change, patch)
    assert_that(actual_top).is_equal_to(expected_result_top)
    actual_message = fail_reason_managed_placement_group(change, patch)
    assert_that(actual_message).is_equal_to(expected_message)


@pytest.mark.parametrize(
    "base_config, target_config, change, expected_subnet_updated, expected_fail_reason, expected_action_needed",
    [
        # If change includes SubnetIds and existing + new cluster configuration uses the same managed Fsx for Lustre
        #   - Show Managed Fsx validation failure message
        (
            {
                "Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-12345678"]}}]},
                "SharedStorage": [
                    {"MountDir": "/test-fsx-lustre", "Name": "test-fsx-lustre", "StorageType": "FsxLustre"}
                ],
            },
            {
                "Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-87654321"]}}]},
                "SharedStorage": [
                    {"MountDir": "/test-fsx-lustre", "Name": "test-fsx-lustre", "StorageType": "FsxLustre"}
                ],
            },
            Change(
                path=["SlurmQueues[mock-q]", "Networking"],
                key="SubnetIds",
                old_value=["subnet-12345678"],
                new_value=["subnet-87654321"],
                update_policy={},
                is_list=False,
            ),
            False,
            "SubnetIds configuration cannot be updated when a managed FSx for Lustre file system is configured. "
            "Forcing an update would trigger a deletion of the existing file system and result in potential data loss",
            "If you intend to preserve the same file system or you want to create a new one please refer to the "
            "shared storage section in ParallelCluster user guide.",
        ),
        # If update includes SubnetIds and existing cluster configuration uses an External Fsx for Lustre FS
        #   - Fall back to QueueUpdateStrategy Update Policy failure message
        (
            {
                "Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-12345678"]}}]},
                "SharedStorage": [
                    {
                        "MountDir": "/test-fsx-lustre",
                        "FsxLustreSettings": {"FileSystemId": "test-fsx-lustre-id"},
                        "StorageType": "FsxLustre",
                    }
                ],
            },
            {
                "Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-87654321"]}}]},
                "SharedStorage": [
                    {
                        "MountDir": "/test-fsx-lustre",
                        "FsxLustreSettings": {"FileSystemId": "test-fsx-lustre-id"},
                        "StorageType": "FsxLustre",
                    }
                ],
            },
            Change(
                path=["SlurmQueues[mock-q]", "Networking"],
                key="SubnetIds",
                old_value=["subnet-12345678"],
                new_value=["subnet-87654321"],
                update_policy={},
                is_list=False,
            ),
            False,
            "All compute nodes must be stopped or QueueUpdateStrategy must be set",
            "Stop the compute fleet with the pcluster update-compute-fleet command, or set QueueUpdateStrategy in the "
            "configuration used for the 'update-cluster' operation",
        ),
        # If change includes SubnetIds and existing + new cluster configuration does not have an Fsx FileSystem
        #   - Fall back to QueueUpdateStrategy Update Policy failure message
        (
            {
                "Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-12345678"]}}]},
                "SharedStorage": [
                    {"MountDir": "/test-efs", "Name": "test-efs", "StorageType": "Efs"},
                    {"MountDir": "/test-ebs", "Name": "test-ebs", "StorageType": "Ebs"},
                ],
            },
            {
                "Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-87654321"]}}]},
                "SharedStorage": [
                    {"MountDir": "/test-efs", "Name": "test-efs", "StorageType": "Efs"},
                    {"MountDir": "/test-ebs", "Name": "test-ebs", "StorageType": "Ebs"},
                ],
            },
            Change(
                path=["SlurmQueues[mock-q]", "Networking"],
                key="SubnetIds",
                old_value=["subnet-12345678"],
                new_value=["subnet-87654321"],
                update_policy={},
                is_list=False,
            ),
            False,
            "All compute nodes must be stopped or QueueUpdateStrategy must be set",
            "Stop the compute fleet with the pcluster update-compute-fleet command, or set QueueUpdateStrategy in the "
            "configuration used for the 'update-cluster' operation",
        ),
        # If change includes SubnetIds and existing managed Fsx FileSystem is updated to unmanaged Fsx FileSystem
        #   - Fall back to QueueUpdateStrategy Update Policy failure message
        (
            {
                "Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-12345678"]}}]},
                "SharedStorage": [
                    {
                        "MountDir": "/test-fsx-lustre",
                        "FsxLustreSettings": {"FileSystemId": "test-fsx-lustre-id"},
                        "StorageType": "FsxLustre",
                    }
                ],
            },
            {
                "Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-87654321"]}}]},
                "SharedStorage": [
                    {"MountDir": "/test-fsx-lustre", "Name": "test-fsx-lustre", "StorageType": "FsxLustre"},
                ],
            },
            Change(
                path=["SlurmQueues[mock-q]", "Networking"],
                key="SubnetIds",
                old_value=["subnet-12345678"],
                new_value=["subnet-87654321"],
                update_policy={},
                is_list=False,
            ),
            False,
            "All compute nodes must be stopped or QueueUpdateStrategy must be set",
            "Stop the compute fleet with the pcluster update-compute-fleet command, or set QueueUpdateStrategy in the "
            "configuration used for the 'update-cluster' operation",
        ),
        # If SubnetIds is updated and the existing cluster has a managed Fsx FileSystem
        # and an unmanaged Fsx FileSystem is added:
        #   - Show Managed Fsx validation failure message
        (
            {
                "Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-12345678"]}}]},
                "SharedStorage": [
                    {"MountDir": "/test-fsx-lustre", "Name": "test-fsx-lustre", "StorageType": "FsxLustre"},
                ],
            },
            {
                "Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-87654321"]}}]},
                "SharedStorage": [
                    {
                        "MountDir": "/test-fsx-lustre-unmanaged",
                        "FsxLustreSettings": {"FileSystemId": "test-fsx-lustre-id"},
                        "StorageType": "FsxLustre",
                    },
                    {"MountDir": "/test-fsx-lustre", "Name": "test-fsx-lustre", "StorageType": "FsxLustre"},
                ],
            },
            Change(
                path=["SlurmQueues[mock-q]", "Networking"],
                key="SubnetIds",
                old_value=["subnet-12345678"],
                new_value=["subnet-87654321"],
                update_policy={},
                is_list=False,
            ),
            False,
            "SubnetIds configuration cannot be updated when a managed FSx for Lustre file system is configured. "
            "Forcing an update would trigger a deletion of the existing file system and result in potential data loss",
            "If you intend to preserve the same file system or you want to create a new one please refer to the "
            "shared storage section in ParallelCluster user guide.",
        ),
        # If change includes addition of SubnetIds and existing + new cluster configuration uses the same
        # managed Fsx for Lustre
        #   - Show Managed Fsx validation failure message
        (
            {
                "Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-12345678"]}}]},
                "SharedStorage": [
                    {"MountDir": "/test-fsx-lustre", "Name": "test-fsx-lustre", "StorageType": "FsxLustre"}
                ],
            },
            {
                "Scheduling": {
                    "Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-12345678", "subnet-87654321"]}}]
                },
                "SharedStorage": [
                    {"MountDir": "/test-fsx-lustre", "Name": "test-fsx-lustre", "StorageType": "FsxLustre"}
                ],
            },
            Change(
                path=["SlurmQueues[mock-q]", "Networking"],
                key="SubnetIds",
                old_value=["subnet-12345678"],
                new_value=["subnet-12345678", "subnet-87654321"],
                update_policy={},
                is_list=False,
            ),
            False,
            "SubnetIds configuration cannot be updated when a managed FSx for Lustre file system is configured. "
            "Forcing an update would trigger a deletion of the existing file system and result in potential data loss",
            "If you intend to preserve the same file system or you want to create a new one please refer to the "
            "shared storage section in ParallelCluster user guide.",
        ),
        # If change includes removal of SubnetIds and existing + new cluster configuration uses the same
        # managed Fsx for Lustre
        #   - Show Managed Fsx validation failure message
        (
            {
                "Scheduling": {
                    "Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-12345678", "subnet-87654321"]}}]
                },
                "SharedStorage": [
                    {"MountDir": "/test-fsx-lustre", "Name": "test-fsx-lustre", "StorageType": "FsxLustre"}
                ],
            },
            {
                "Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-12345678"]}}]},
                "SharedStorage": [
                    {"MountDir": "/test-fsx-lustre", "Name": "test-fsx-lustre", "StorageType": "FsxLustre"}
                ],
            },
            Change(
                path=["SlurmQueues[mock-q]", "Networking"],
                key="SubnetIds",
                old_value=["subnet-12345678", "subnet-87654321"],
                new_value=["subnet-12345678"],
                update_policy={},
                is_list=False,
            ),
            False,
            "SubnetIds configuration cannot be updated when a managed FSx for Lustre file system is configured. "
            "Forcing an update would trigger a deletion of the existing file system and result in potential data loss",
            "If you intend to preserve the same file system or you want to create a new one please refer to the "
            "shared storage section in ParallelCluster user guide.",
        ),
        # If change includes removal of SubnetIds and no managed Fsx FileSystem is present
        #   - Fall back to QueueUpdateStrategy Update Policy failure message
        (
            {
                "Scheduling": {
                    "Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-12345678", "subnet-87654321"]}}]
                },
                "SharedStorage": [
                    {
                        "MountDir": "/test-fsx-lustre-unmanaged",
                        "FsxLustreSettings": {"FileSystemId": "test-fsx-lustre-id"},
                        "StorageType": "FsxLustre",
                    },
                ],
            },
            {
                "Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-87654321"]}}]},
                "SharedStorage": [
                    {
                        "MountDir": "/test-fsx-lustre-unmanaged",
                        "FsxLustreSettings": {"FileSystemId": "test-fsx-lustre-id"},
                        "StorageType": "FsxLustre",
                    },
                    {"MountDir": "/test-fsx-lustre", "Name": "test-fsx-lustre", "StorageType": "FsxLustre"},
                ],
            },
            Change(
                path=["SlurmQueues[mock-q]", "Networking"],
                key="SubnetIds",
                old_value=["subnet-12345678", "subnet-87654321"],
                new_value=["subnet-87654321"],
                update_policy={},
                is_list=False,
            ),
            False,
            "All compute nodes must be stopped or QueueUpdateStrategy must be set",
            "Stop the compute fleet with the pcluster update-compute-fleet command, or set QueueUpdateStrategy in the "
            "configuration used for the 'update-cluster' operation",
        ),
        # If change includes addition of SubnetIds and no managed Fsx FileSystem is present
        #   - Fall back to QueueUpdateStrategy Update Policy failure message but update is possible
        (
            {
                "Scheduling": {"Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-12345678"]}}]},
            },
            {
                "Scheduling": {
                    "Queues": [{"Name": "mock-q", "Networking": {"SubnetIds": ["subnet-12345678", "subnet-87654321"]}}]
                },
                "SharedStorage": [
                    {
                        "MountDir": "/test-fsx-lustre-unmanaged",
                        "FsxLustreSettings": {"FileSystemId": "test-fsx-lustre-id"},
                        "StorageType": "FsxLustre",
                    },
                    {"MountDir": "/test-fsx-lustre", "Name": "test-fsx-lustre", "StorageType": "FsxLustre"},
                ],
            },
            Change(
                path=["SlurmQueues[mock-q]", "Networking"],
                key="SubnetIds",
                old_value=["subnet-12345678"],
                new_value=["subnet-12345678", "subnet-87654321"],
                update_policy={},
                is_list=False,
            ),
            True,
            "All compute nodes must be stopped or QueueUpdateStrategy must be set",
            "Stop the compute fleet with the pcluster update-compute-fleet command, or set QueueUpdateStrategy in the "
            "configuration used for the 'update-cluster' operation",
        ),
    ],
)
def test_condition_checker_managed_fsx(
    mocker,
    base_config,
    target_config,
    change,
    expected_subnet_updated,
    expected_fail_reason,
    expected_action_needed,
):
    cluster = Cluster(name="mock-name", stack="mock-stack")
    mocker.patch.object(cluster, "has_running_capacity", return_value=True)
    patch = ConfigPatch(cluster=cluster, base_config=base_config, target_config=target_config)
    assert_that(condition_checker_managed_fsx(change, patch)).is_equal_to(expected_subnet_updated)
    assert_that(fail_reason_managed_fsx(change, patch)).is_equal_to(expected_fail_reason)
    assert_that(actions_needed_managed_fsx(change, patch)).is_equal_to(expected_action_needed)


@pytest.mark.parametrize(
    "key, path, old_value, new_value, expected_running_login_nodes, expected_update_allowed, "
    "expected_fail_reason, expected_actions_needed",
    [
        pytest.param(
            "Pools",
            ["LoginNodes"],
            {
                "Name": "pool-old",
                "InstanceType": "t2.micro",
                "GracetimePeriod": 3,
                "Count": 1,
                "Networking": {"SubnetIds": ["subnet-12345678901234567"]},
                "Ssh": {"KeyName": "valid-key"},
            },
            None,
            True,
            False,
            "The update is not supported when login nodes are running",
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            id="Login nodes must be stopped to remove a pool",
        ),
        pytest.param(
            "Pools",
            ["LoginNodes"],
            {
                "Name": "pool-old",
                "InstanceType": "t2.micro",
                "GracetimePeriod": 3,
                "Count": 1,
                "Networking": {"SubnetIds": ["subnet-12345678901234567"]},
                "Ssh": {"KeyName": "valid-key"},
            },
            None,
            False,
            True,
            None,
            None,
            id="Login pools can be removed when Login Nodes stopped",
        ),
        pytest.param(
            "Pools",
            ["LoginNodes"],
            None,
            {
                "Name": "pool-new",
                "InstanceType": "t2.micro",
                "GracetimePeriod": 3,
                "Count": 1,
                "Networking": {"SubnetIds": ["subnet-12345678901234567"]},
                "Ssh": {"KeyName": "valid-key"},
            },
            True,
            True,
            None,
            None,
            id="Login pools can be added",
        ),
        pytest.param(
            "Pools",
            ["LoginNodes"],
            None,
            {
                "Name": "pool-new",
                "InstanceType": "t2.micro",
                "GracetimePeriod": 3,
                "Count": 1,
                "Networking": {"SubnetIds": ["subnet-12345678901234567"]},
                "Ssh": {"KeyName": "valid-key"},
            },
            False,
            True,
            None,
            None,
            id="Login pools can be added",
        ),
    ],
)
def test_login_nodes_pools_policy(
    mocker,
    key,
    path,
    old_value,
    new_value,
    expected_running_login_nodes,
    expected_update_allowed,
    expected_fail_reason,
    expected_actions_needed,
):
    cluster = dummy_cluster()
    mocker.patch.object(cluster, "has_running_login_nodes", return_value=expected_running_login_nodes)

    patch_mock = mocker.MagicMock()
    patch_mock.cluster = cluster
    change_mock = mocker.MagicMock()
    change_mock.path = path
    change_mock.key = key
    change_mock.old_value = old_value
    change_mock.new_value = new_value

    assert_that(UpdatePolicy.LOGIN_NODES_POOLS.condition_checker(change_mock, patch_mock)).is_equal_to(
        expected_update_allowed
    )
    if not expected_update_allowed:
        assert_that(UpdatePolicy.LOGIN_NODES_POOLS.fail_reason(change_mock, patch_mock)).is_equal_to(
            expected_fail_reason
        )
        assert_that(UpdatePolicy.LOGIN_NODES_POOLS.action_needed(change_mock, patch_mock)).is_equal_to(
            expected_actions_needed
        )


@pytest.mark.parametrize(
    "base_config, target_config, change, login_nodes_running, "
    "expected_update_allowed, expected_fail_reason, expected_action_needed",
    [
        pytest.param(
            {
                "LoginNodes": {"Pools": [{"Name": "mock-lp1", "Ssh": {"KeyName": "mock-kn1"}}]},
            },
            {
                "LoginNodes": {"Pools": [{"Name": "mock-lp1", "Ssh": {"KeyName": "mock-kn2"}}]},
            },
            Change(
                path=["LoginNodes", "Pools[mock-lp1]", "Ssh"],
                key="KeyName",
                old_value="mock-kn1",
                new_value="mock-kn2",
                update_policy={},
                is_list=False,
            ),
            False,
            True,
            None,
            None,
            id="Login nodes parameter covered by the policy can be updated when login nodes are stopped",
        ),
        pytest.param(
            {
                "LoginNodes": {"Pools": [{"Name": "mock-lp1", "Ssh": {"KeyName": "mock-kn1"}}]},
            },
            {
                "LoginNodes": {"Pools": [{"Name": "mock-lp1", "Ssh": {"KeyName": "mock-kn2"}}]},
            },
            Change(
                path=["LoginNodes", "Pools[mock-lp1]", "Ssh"],
                key="KeyName",
                old_value="mock-kn1",
                new_value="mock-kn2",
                update_policy={},
                is_list=False,
            ),
            True,
            False,
            "The update is not supported when login nodes are running",
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            id="Login nodes parameter covered by the policy cannot be updated when login nodes are running",
        ),
    ],
)
def test_login_nodes_stop_policy(
    mocker,
    base_config,
    target_config,
    change,
    login_nodes_running,
    expected_update_allowed,
    expected_fail_reason,
    expected_action_needed,
):
    update_policy = UpdatePolicy.LOGIN_NODES_STOP
    cluster = Cluster(name="mock-name", stack="mock-stack")
    mocker.patch.object(cluster, "has_running_login_nodes", return_value=login_nodes_running)
    patch = ConfigPatch(cluster=cluster, base_config=base_config, target_config=target_config)
    assert_that(update_policy.condition_checker(change, patch)).is_equal_to(expected_update_allowed)
    if not expected_update_allowed:
        assert_that(update_policy.fail_reason(change, patch)).is_equal_to(expected_fail_reason)
        assert_that(update_policy.action_needed(change, patch)).is_equal_to(expected_action_needed)


@pytest.mark.parametrize(
    "base_config, target_config, change, compute_nodes_running, login_nodes_running,"
    "expected_update_allowed, expected_fail_reason, expected_action_needed",
    [
        pytest.param(
            {
                "DirectoryService": {"DomainName": "dn-1"},
            },
            {
                "DirectoryService": {"DomainName": "dn-2"},
            },
            Change(
                path=["DirectoryService", "DomainName"],
                key="DomainName",
                old_value="dn-1",
                new_value="dn-2",
                update_policy={},
                is_list=False,
            ),
            False,
            False,
            True,
            None,
            None,
            id="The parameter covered by the policy can be updated when login nodes and compute nodes are not running",
        ),
        pytest.param(
            {
                "DirectoryService": {"DomainName": "dn-1"},
            },
            {
                "DirectoryService": {"DomainName": "dn-2"},
            },
            Change(
                path=["DirectoryService", "DomainName"],
                key="DomainName",
                old_value="dn-1",
                new_value="dn-2",
                update_policy={},
                is_list=False,
            ),
            True,
            True,
            False,
            "The update is not supported when compute or login nodes are running",
            "Stop the compute fleet with the pcluster update-compute-fleet command. "
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            id="The parameter covered by the policy cannot be updated when login nodes and compute nodes are running",
        ),
        pytest.param(
            {
                "DirectoryService": {"DomainName": "dn-1"},
            },
            {
                "DirectoryService": {"DomainName": "dn-2"},
            },
            Change(
                path=["DirectoryService", "DomainName"],
                key="DomainName",
                old_value="dn-1",
                new_value="dn-2",
                update_policy={},
                is_list=False,
            ),
            True,
            False,
            False,
            "The update is not supported when compute or login nodes are running",
            "Stop the compute fleet with the pcluster update-compute-fleet command. "
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            id="The parameter covered by the policy cannot be updated when compute nodes are running",
        ),
        pytest.param(
            {
                "DirectoryService": {"DomainName": "dn-1"},
            },
            {
                "DirectoryService": {"DomainName": "dn-2"},
            },
            Change(
                path=["DirectoryService", "DomainName"],
                key="DomainName",
                old_value="dn-1",
                new_value="dn-2",
                update_policy={},
                is_list=False,
            ),
            False,
            True,
            False,
            "The update is not supported when compute or login nodes are running",
            "Stop the compute fleet with the pcluster update-compute-fleet command. "
            "Stop the login nodes by setting Count parameter to 0 "
            "and update the cluster with the pcluster update-cluster command",
            id="The parameter covered by the policy cannot be updated when login nodes are running",
        ),
    ],
)
def test_compute_and_login_nodes_stop_policy(
    mocker,
    base_config,
    target_config,
    change,
    compute_nodes_running,
    login_nodes_running,
    expected_update_allowed,
    expected_fail_reason,
    expected_action_needed,
):
    update_policy = UpdatePolicy.COMPUTE_AND_LOGIN_NODES_STOP
    cluster = Cluster(name="mock-name", stack="mock-stack")
    mocker.patch.object(cluster, "has_running_capacity", return_value=compute_nodes_running)
    mocker.patch.object(cluster, "has_running_login_nodes", return_value=login_nodes_running)
    patch = ConfigPatch(cluster=cluster, base_config=base_config, target_config=target_config)
    assert_that(update_policy.condition_checker(change, patch)).is_equal_to(expected_update_allowed)
    if not expected_update_allowed:
        assert_that(update_policy.fail_reason(change, patch)).is_equal_to(expected_fail_reason)
        assert_that(update_policy.action_needed(change, patch)).is_equal_to(expected_action_needed)


@pytest.mark.parametrize(
    "old_storage_value, new_storage_value, expected_condition, expected_fail_reason, expected_action_needed",
    [
        pytest.param(
            "/home",
            "dummy",
            False,
            "The /home directory cannot be changed during an update",
            "Please revert any changes to the /home mount",
        ),
        pytest.param(
            "home",
            "dummy",
            False,
            "The /home directory cannot be changed during an update",
            "Please revert any changes to the /home mount",
        ),
        pytest.param(
            "dummy",
            "home",
            False,
            "The /home directory cannot be changed during an update",
            "Please revert any changes to the /home mount",
        ),
        pytest.param(
            "dummy",
            "/home",
            False,
            "The /home directory cannot be changed during an update",
            "Please revert any changes to the /home mount",
        ),
        pytest.param(
            "dummy",
            "not_home",
            True,
            None,
            None,
        ),
    ],
)
def test_home_change_policy(
    mocker, old_storage_value, new_storage_value, expected_condition, expected_fail_reason, expected_action_needed
):
    cluster = dummy_cluster()
    mocker.patch.object(cluster, "has_running_capacity", return_value=False)
    patch_mock = mocker.MagicMock()
    change_mock = mocker.MagicMock()
    change_mock.new_value = {"MountDir": new_storage_value}
    change_mock.old_value = {"MountDir": old_storage_value}
    change_mock.key = "SharedStorage"

    patch_mock.cluster = cluster
    assert_that(UpdatePolicy.SHARED_STORAGE_UPDATE_POLICY.condition_checker(change_mock, patch_mock)).is_equal_to(
        expected_condition
    )
    if expected_condition is False:
        assert_that(UpdatePolicy.SHARED_STORAGE_UPDATE_POLICY.fail_reason(change_mock, patch_mock)).is_equal_to(
            expected_fail_reason
        )
        assert_that(UpdatePolicy.SHARED_STORAGE_UPDATE_POLICY.action_needed(change_mock, patch_mock)).is_equal_to(
            expected_action_needed
        )
