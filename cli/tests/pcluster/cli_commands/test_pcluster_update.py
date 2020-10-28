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

from pcluster.cli_commands.update import _format_report_column, _get_target_config_tags_list


@pytest.mark.parametrize(
    "value, expected_output",
    [
        (None, "-"),
        (False, "False"),
        (True, "True"),
        ("Long long long long long long text", "Long long long long long lo..."),
    ],
)
def test_format_change_value(value, expected_output):
    assert_that(_format_report_column(value)).is_equal_to(expected_output)


@pytest.mark.parametrize("config_file_tags", [{}, {"Version": "NotInstalledVersion"}])
def test_get_target_config_tags_list(mocker, config_file_tags):
    """Verify that the function to get the tags list used when updating a cluster behaves as expected."""
    installed_version = "FakeInstalledVersion"
    tags = {"Version": installed_version}
    tags.update(config_file_tags)
    expected_tags_list = [{"Key": tag_name, "Value": tag_value} for tag_name, tag_value in tags.items()]
    get_version_patch = mocker.patch(
        "pcluster.cli_commands.update.utils.get_installed_version", return_value=installed_version
    )
    mocked_config = mocker.MagicMock()
    mocked_config.get_section("cluster").get_param_value.side_effect = lambda param: {"tags": config_file_tags}.get(
        param
    )
    observed_tags_list = _get_target_config_tags_list(mocked_config)
    assert_that(get_version_patch.call_count).is_equal_to(1)
    assert_that(observed_tags_list).is_equal_to(expected_tags_list)
