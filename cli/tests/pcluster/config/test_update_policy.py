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
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1]", "ComputeResources[compute1]"],
            10,
            9,
            None,
            True,
            id="stopped fleet and new_min < old_min",
        ),
        pytest.param(
            True,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue2]", "ComputeResources[compute2]"],
            10,
            11,
            None,
            True,
            id="stopped fleet new_min > old_min",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1]", "ComputeResources[compute1]"],
            10,
            9,
            None,
            False,
            id="running fleet and new_min < old_min with no update strategy set",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue2]", "ComputeResources[compute2]"],
            10,
            11,
            None,
            False,
            id="running fleet and new_min > old_min with no update strategy set",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue3]", "ComputeResources[compute3]"],
            None,
            0,
            None,
            False,
            id="running fleet and new_min = DEFAULT_MIN_COUNT with no update strategy set",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue4]", "ComputeResources[compute4]"],
            None,
            11,
            None,
            False,
            id="running fleet and new_min > DEFAULT_MIN_COUNT with no update strategy set",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue5]", "ComputeResources[compute5]"],
            11,
            None,
            None,
            False,
            id="running fleet and DEFAULT_MIN_COUNT < old_min with no update strategy set",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue6]", "ComputeResources[compute6]"],
            0,
            None,
            None,
            False,
            id="running fleet and DEFAULT_MIN_COUNT = old_min with no update strategy set",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1]", "ComputeResources[compute1]"],
            10,
            9,
            QueueUpdateStrategy.COMPUTE_FLEET_STOP.value,
            False,
            id="running fleet and new_min < old_min with update strategy COMPUTE_FLEET_STOP",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue2]", "ComputeResources[compute2]"],
            10,
            11,
            QueueUpdateStrategy.COMPUTE_FLEET_STOP.value,
            False,
            id="running fleet and new_min > old_min with update strategy COMPUTE_FLEET_STOP",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue3]", "ComputeResources[compute3]"],
            None,
            0,
            QueueUpdateStrategy.COMPUTE_FLEET_STOP.value,
            False,
            id="running fleet and new_min = DEFAULT_MIN_COUNT with update strategy COMPUTE_FLEET_STOP",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue4]", "ComputeResources[compute4]"],
            None,
            11,
            QueueUpdateStrategy.COMPUTE_FLEET_STOP.value,
            False,
            id="running fleet and new_min > DEFAULT_MIN_COUNT with update strategy COMPUTE_FLEET_STOP",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue5]", "ComputeResources[compute5]"],
            11,
            None,
            QueueUpdateStrategy.COMPUTE_FLEET_STOP.value,
            False,
            id="running fleet and DEFAULT_MIN_COUNT < old_min with update strategy COMPUTE_FLEET_STOP",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue6]", "ComputeResources[compute6]"],
            0,
            None,
            QueueUpdateStrategy.COMPUTE_FLEET_STOP.value,
            False,
            id="running fleet and DEFAULT_MIN_COUNT = old_min with update strategy COMPUTE_FLEET_STOP",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue1]", "ComputeResources[compute1]"],
            10,
            9,
            QueueUpdateStrategy.DRAIN.value,
            True,
            id="running fleet and new_min < old_min with update strategy DRAIN",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue2]", "ComputeResources[compute2]"],
            10,
            11,
            QueueUpdateStrategy.DRAIN.value,
            True,
            id="running fleet and new_min > old_min with update strategy DRAIN",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue3]", "ComputeResources[compute3]"],
            None,
            0,
            QueueUpdateStrategy.DRAIN.value,
            True,
            id="running fleet and new_min = DEFAULT_MIN_COUNT with update strategy DRAIN",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue4]", "ComputeResources[compute4]"],
            None,
            11,
            QueueUpdateStrategy.DRAIN.value,
            True,
            id="running fleet and new_min > DEFAULT_MIN_COUNT with update strategy DRAIN",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue5]", "ComputeResources[compute5]"],
            11,
            None,
            QueueUpdateStrategy.DRAIN.value,
            True,
            id="running fleet and DEFAULT_MIN_COUNT < old_min with update strategy DRAIN",
        ),
        pytest.param(
            False,
            "MinCount",
            ["Scheduling", "SlurmQueues[queue6]", "ComputeResources[compute6]"],
            0,
            None,
            QueueUpdateStrategy.DRAIN.value,
            True,
            id="running fleet and DEFAULT_MIN_COUNT = old_min with update strategy DRAIN",
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

    assert_that(UpdatePolicy.COMPUTE_FLEET_STOP.condition_checker(change_mock, patch_mock)).is_equal_to(expected_result)
    cluster_has_running_capacity_mock.assert_called()


@pytest.mark.parametrize(
    "key, path, old_value, new_value, expected_fail_reason, expected_actions_needed",
    [
        pytest.param(
            "MinCount",
            ["Scheduling", "SlurmQueues[queue6]", "ComputeResources[compute6]"],
            0,
            None,
            "All compute nodes must be stopped or queue update strategy must be set",
            "Stop the compute fleet with the pcluster update-compute-fleet command "
            "or set QueueUpdateStrategy in the configuration used for the 'update-cluster' operation",
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

    assert_that(UpdatePolicy.COMPUTE_FLEET_STOP.fail_reason(change_mock, patch_mock)).is_equal_to(expected_fail_reason)
    assert_that(UpdatePolicy.COMPUTE_FLEET_STOP.action_needed(change_mock, patch_mock)).is_equal_to(
        expected_actions_needed
    )
