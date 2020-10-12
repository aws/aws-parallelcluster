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

from pcluster.config.update_policy import UpdatePolicy


@pytest.mark.parametrize(
    "is_fleet_stopped, old_max, new_max, expected_result",
    [(True, 10, 11, True), (True, 10, 9, True), (False, 10, 9, False), (False, 10, 11, True)],
)
def test_max_count_policy(mocker, is_fleet_stopped, old_max, new_max, expected_result):
    cluster_has_running_capacity_mock = mocker.patch(
        "pcluster.utils.cluster_has_running_capacity", return_value=not is_fleet_stopped
    )
    patch_mock = mocker.MagicMock()
    patch_mock.stack_name = "stack_name"
    change_mock = mocker.MagicMock()
    change_mock.new_value = new_max
    change_mock.old_value = old_max

    assert_that(UpdatePolicy.MAX_COUNT.condition_checker(change_mock, patch_mock)).is_equal_to(expected_result)
    cluster_has_running_capacity_mock.assert_called_with("stack_name")


@pytest.mark.parametrize(
    "is_fleet_stopped, old_min_max, new_min_max, expected_result",
    [
        (True, (0, 10), (1, 10), True),
        (True, (1, 10), (0, 10), True),
        (False, (0, 10), (1, 10), False),
        (False, (1, 10), (0, 10), False),
        (False, (0, 10), (1, 11), True),
        (False, (0, 10), (1, 12), True),
    ],
)
def test_min_count_policy(mocker, is_fleet_stopped, old_min_max, new_min_max, expected_result):
    cluster_has_running_capacity_mock = mocker.patch(
        "pcluster.utils.cluster_has_running_capacity", return_value=not is_fleet_stopped
    )
    patch_mock = mocker.MagicMock()
    patch_mock.stack_name = "stack_name"
    base_config_section_mock = mocker.MagicMock()
    base_config_section_mock.get_param_value = mocker.MagicMock(return_value=old_min_max[1])
    patch_mock.base_config.get_section = mocker.MagicMock(return_value=base_config_section_mock)
    target_config_section_mock = mocker.MagicMock()
    target_config_section_mock.get_param_value = mocker.MagicMock(return_value=new_min_max[1])
    patch_mock.target_config.get_section = mocker.MagicMock(return_value=target_config_section_mock)
    change_mock = mocker.MagicMock()
    change_mock.new_value = new_min_max[0]
    change_mock.old_value = old_min_max[0]

    assert_that(UpdatePolicy.MIN_COUNT.condition_checker(change_mock, patch_mock)).is_equal_to(expected_result)
    cluster_has_running_capacity_mock.assert_called_with("stack_name")
