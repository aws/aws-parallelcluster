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
from pcluster.config.update_policy import UpdatePolicy
from tests.pcluster.test_utils import dummy_cluster


@pytest.mark.parametrize(
    "is_fleet_stopped, old_max, new_max, expected_result",
    [
        pytest.param(True, 10, 9, True, id="stopped fleet and new_max < old_max"),
        pytest.param(True, 10, 11, True, id="stopped fleet new_max > old_max"),
        pytest.param(False, 10, 9, False, id="running fleet and new_max < old_max"),
        pytest.param(False, 10, 11, True, id="running fleet and new_max > old_max"),
        pytest.param(False, None, 0, False, id="running fleet and new_max < DEFAULT_MAX_COUNT"),
        pytest.param(False, None, 11, True, id="running fleet and new_max > DEFAULT_MAX_COUNT"),
        pytest.param(False, 11, None, False, id="running fleet and DEFAULT_MAX_COUNT < old_max"),
        pytest.param(False, 0, None, True, id="running fleet and DEFAULT_MAX_COUNT > old_max"),
    ],
)
def test_max_count_policy(mocker, is_fleet_stopped, old_max, new_max, expected_result):
    cluster = dummy_cluster()
    cluster_has_running_capacity_mock = mocker.patch.object(
        cluster, "has_running_capacity", return_value=not is_fleet_stopped
    )

    patch_mock = mocker.MagicMock()
    patch_mock.cluster = cluster
    change_mock = mocker.MagicMock()
    change_mock.new_value = new_max
    change_mock.old_value = old_max

    assert_that(UpdatePolicy.MAX_COUNT.condition_checker(change_mock, patch_mock)).is_equal_to(expected_result)
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
            "SlurmQueues",
            ["Scheduling"],
            None,
            {
                "Name": "queue-added",
                "Networking": {"SubnetIds": "subnet-12345678"},
                "ComputeResources": {"Name": "compute-added", "InstanceType": "c5.9xlarge"},
            },
            True,
            id="stopped fleet and queue is added",
        ),
        pytest.param(
            True,
            "SlurmQueues",
            ["Scheduling"],
            {
                "Name": "queue-removed",
                "Networking": {"SubnetIds": "subnet-12345678"},
                "ComputeResources": {"Name": "compute-removed", "InstanceType": "c5.9xlarge"},
            },
            None,
            True,
            id="stopped fleet and queue is removed",
        ),
        pytest.param(
            True,
            "ComputeResources",
            ["Scheduling", "SlurmQueues[queue1]"],
            None,
            {"Name": "compute-added", "InstanceType": "c5.large", "MinCount": 1},
            True,
            id="stopped fleet and compute is added",
        ),
        pytest.param(
            True,
            "ComputeResources",
            ["Scheduling", "SlurmQueues[queue1]"],
            {"Name": "compute-removed", "InstanceType": "c5.large", "MinCount": 1},
            None,
            True,
            id="stopped fleet and compute is removed",
        ),
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
            True,
            id="running fleet and queue is added",
        ),
        pytest.param(
            False,
            "SlurmQueues",
            ["Scheduling"],
            {
                "Name": "queue-removed",
                "Networking": {"SubnetIds": "subnet-12345678"},
                "ComputeResources": {"Name": "compute-removed", "InstanceType": "c5.9xlarge"},
            },
            None,
            False,
            id="running fleet and queue is removed",
        ),
        pytest.param(
            False,
            "ComputeResources",
            ["Scheduling", "SlurmQueues[queue1]"],
            None,
            {"Name": "compute-added", "InstanceType": "c5.large", "MinCount": 1},
            True,
            id="running fleet and compute is added",
        ),
        pytest.param(
            False,
            "ComputeResources",
            ["Scheduling", "SlurmQueues[queue1]"],
            {"Name": "compute-removed", "InstanceType": "c5.large", "MinCount": 1},
            None,
            False,
            id="running fleet and compute is removed",
        ),
    ],
)
def test_compute_fleet_stop_on_remove_condition_checker(
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
                "Name": "queue-removed",
                "Networking": {"SubnetIds": "subnet-12345678"},
                "ComputeResources": {"Name": "compute-removed", "InstanceType": "c5.9xlarge"},
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
