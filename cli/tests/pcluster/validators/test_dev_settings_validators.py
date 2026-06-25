# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from pcluster.validators.common import FailureLevel
from pcluster.validators.dev_settings_validators import (
    CliAttributeOverridesValidator,
    ExtraChefAttributesValidator,
)
from tests.pcluster.validators.utils import assert_failure_level, assert_failure_messages


@pytest.mark.parametrize(
    "extra_chef_attributes, expected_message, expected_failure_level",
    [
        pytest.param(
            '{"cluster": {"slurm": {"reconfigure_timeout": 600}}}',
            None,
            None,
            id="reconfigure_timeout valid integer > 300",
        ),
        pytest.param(
            '{"cluster": {"slurm": {"reconfigure_timeout": 301}}}',
            None,
            None,
            id="reconfigure_timeout valid integer just above 300",
        ),
        pytest.param(
            '{"cluster": {"slurm": {"reconfigure_timeout": 300}}}',
            "Invalid value in DevSettings/Cookbook/ExtraChefAttributes: "
            "attribute 'cluster.slurm.reconfigure_timeout' must be greater than 300.",
            FailureLevel.ERROR,
            id="reconfigure_timeout equal to 300 throws error",
        ),
        pytest.param(
            '{"cluster": {"slurm": {"reconfigure_timeout": 100}}}',
            "Invalid value in DevSettings/Cookbook/ExtraChefAttributes: "
            "attribute 'cluster.slurm.reconfigure_timeout' must be greater than 300.",
            FailureLevel.ERROR,
            id="reconfigure_timeout less than 300 throws error",
        ),
        pytest.param(
            '{"cluster": {"slurm": {"reconfigure_timeout": 0}}}',
            "Invalid value in DevSettings/Cookbook/ExtraChefAttributes: "
            "attribute 'cluster.slurm.reconfigure_timeout' must be greater than 300.",
            FailureLevel.ERROR,
            id="reconfigure_timeout zero throws error",
        ),
        pytest.param(
            '{"cluster": {"slurm": {"reconfigure_timeout": -100}}}',
            "Invalid value in DevSettings/Cookbook/ExtraChefAttributes: "
            "attribute 'cluster.slurm.reconfigure_timeout' must be greater than 300.",
            FailureLevel.ERROR,
            id="reconfigure_timeout negative throws error",
        ),
        pytest.param(
            '{"cluster": {"slurm": {"reconfigure_timeout": "600"}}}',
            "Invalid value in DevSettings/Cookbook/ExtraChefAttributes: "
            "attribute 'cluster.slurm.reconfigure_timeout' must be an integer.",
            FailureLevel.ERROR,
            id="reconfigure_timeout string throws error",
        ),
        pytest.param(
            '{"cluster": {"slurm": {"reconfigure_timeout": true}}}',
            "Invalid value in DevSettings/Cookbook/ExtraChefAttributes: "
            "attribute 'cluster.slurm.reconfigure_timeout' must be an integer.",
            FailureLevel.ERROR,
            id="reconfigure_timeout boolean true throws error",
        ),
        pytest.param(
            '{"cluster": {"slurm": {"reconfigure_timeout": false}}}',
            "Invalid value in DevSettings/Cookbook/ExtraChefAttributes: "
            "attribute 'cluster.slurm.reconfigure_timeout' must be an integer.",
            FailureLevel.ERROR,
            id="reconfigure_timeout boolean false throws error",
        ),
        pytest.param(
            '{"cluster": {"slurm": {"reconfigure_timeout": 3.14}}}',
            "Invalid value in DevSettings/Cookbook/ExtraChefAttributes: "
            "attribute 'cluster.slurm.reconfigure_timeout' must be an integer.",
            FailureLevel.ERROR,
            id="reconfigure_timeout float throws error",
        ),
        pytest.param(
            '{"cluster": {"slurm": {"other-setting": "value"}}}',
            None,
            None,
            id="reconfigure_timeout not set passes",
        ),
        pytest.param(
            '{"cluster": {"other": "value"}}',
            None,
            None,
            id="slurm section not present passes",
        ),
    ],
)
def test_extra_chef_attributes_validator_reconfigure_timeout(
    extra_chef_attributes, expected_message, expected_failure_level
):
    actual_failures = ExtraChefAttributesValidator().execute(extra_chef_attributes=extra_chef_attributes)
    assert_failure_messages(actual_failures, expected_message)
    if expected_failure_level:
        assert_failure_level(actual_failures, expected_failure_level)


@pytest.mark.parametrize(
    "extra_chef_attributes, expected_message, expected_failure_level",
    [
        pytest.param(None, None, None, id="No extra chef attributes"),
        pytest.param('{"other_attribute": "value"}', None, None, id="cluster_readiness_check_enabled not set"),
        pytest.param(
            '{"cluster": {"cluster_readiness_check_enabled": "true"}}',
            None,
            None,
            id="cluster_readiness_check_enabled 'true' string passes",
        ),
        pytest.param(
            '{"cluster": {"cluster_readiness_check_enabled": true}}',
            None,
            None,
            id="cluster_readiness_check_enabled true boolean passes",
        ),
        pytest.param(
            '{"cluster": {"cluster_readiness_check_enabled": "false"}}',
            "Cluster readiness check is disabled. Cluster creation and cluster update can succeed "
            "even if there are cluster nodes that did not complete the deployment of the expected configuration.",
            FailureLevel.WARNING,
            id="cluster_readiness_check_enabled 'false' string throws warning",
        ),
        pytest.param(
            '{"cluster": {"cluster_readiness_check_enabled": false}}',
            "Cluster readiness check is disabled. Cluster creation and cluster update can succeed "
            "even if there are cluster nodes that did not complete the deployment of the expected configuration.",
            FailureLevel.WARNING,
            id="cluster_readiness_check_enabled false boolean throws warning",
        ),
        pytest.param(
            '{"cluster": {"cluster_readiness_check_enabled": "invalid"}}',
            "Invalid value in DevSettings/Cookbook/ExtraChefAttributes: "
            "attribute 'cluster.cluster_readiness_check_enabled' must be a boolean value.",
            FailureLevel.ERROR,
            id="cluster_readiness_check_enabled invalid string throws error",
        ),
        pytest.param(
            '{"cluster": {"cluster_readiness_check_enabled": 123}}',
            "Invalid value in DevSettings/Cookbook/ExtraChefAttributes: "
            "attribute 'cluster.cluster_readiness_check_enabled' must be a boolean value.",
            FailureLevel.ERROR,
            id="cluster_readiness_check_enabled invalid number throws error",
        ),
    ],
)
def test_extra_chef_attributes_validator_cluster_readiness_check_enabled(
    extra_chef_attributes, expected_message, expected_failure_level
):
    actual_failures = ExtraChefAttributesValidator().execute(extra_chef_attributes=extra_chef_attributes)
    assert_failure_messages(actual_failures, expected_message)
    if expected_failure_level:
        assert_failure_level(actual_failures, expected_failure_level)


@pytest.mark.parametrize(
    "extra_chef_attributes, expected_message, expected_failure_level",
    [
        pytest.param(None, None, None, id="No extra chef attributes"),
        pytest.param('{"other_attribute": "value"}', None, None, id="cluster_readiness_check_ignore_failure not set"),
        pytest.param(
            '{"cluster": {"cluster_readiness_check_ignore_failure": "false"}}',
            None,
            None,
            id="cluster_readiness_check_ignore_failure 'false' string passes",
        ),
        pytest.param(
            '{"cluster": {"cluster_readiness_check_ignore_failure": false}}',
            None,
            None,
            id="cluster_readiness_check_ignore_failure false boolean passes",
        ),
        pytest.param(
            '{"cluster": {"cluster_readiness_check_ignore_failure": "true"}}',
            "Cluster readiness check failures are ignored. Cluster creation and cluster update can succeed "
            "even if there are cluster nodes that did not complete the deployment of the expected configuration.",
            FailureLevel.WARNING,
            id="cluster_readiness_check_ignore_failure 'true' string throws warning",
        ),
        pytest.param(
            '{"cluster": {"cluster_readiness_check_ignore_failure": true}}',
            "Cluster readiness check failures are ignored. Cluster creation and cluster update can succeed "
            "even if there are cluster nodes that did not complete the deployment of the expected configuration.",
            FailureLevel.WARNING,
            id="cluster_readiness_check_ignore_failure true boolean throws warning",
        ),
        pytest.param(
            '{"cluster": {"cluster_readiness_check_ignore_failure": "invalid"}}',
            "Invalid value in DevSettings/Cookbook/ExtraChefAttributes: "
            "attribute 'cluster.cluster_readiness_check_ignore_failure' must be a boolean value.",
            FailureLevel.ERROR,
            id="cluster_readiness_check_ignore_failure invalid string throws error",
        ),
        pytest.param(
            '{"cluster": {"cluster_readiness_check_ignore_failure": 123}}',
            "Invalid value in DevSettings/Cookbook/ExtraChefAttributes: "
            "attribute 'cluster.cluster_readiness_check_ignore_failure' must be a boolean value.",
            FailureLevel.ERROR,
            id="cluster_readiness_check_ignore_failure invalid number throws error",
        ),
    ],
)
def test_extra_chef_attributes_validator_cluster_readiness_check_ignore_failure(
    extra_chef_attributes, expected_message, expected_failure_level
):
    actual_failures = ExtraChefAttributesValidator().execute(extra_chef_attributes=extra_chef_attributes)
    assert_failure_messages(actual_failures, expected_message)
    if expected_failure_level:
        assert_failure_level(actual_failures, expected_failure_level)


@pytest.mark.parametrize(
    "cli_attribute_overrides, expected_message, expected_failure_level",
    [
        pytest.param("", None, None, id="empty string is valid"),
        pytest.param(None, None, None, id="None is valid"),
        pytest.param(
            '{"cinc_version": "18.8.54", "cinc_installer_url": "https://omnitruck.cinc.sh/install.sh"}',
            None,
            None,
            id="valid JSON object",
        ),
        pytest.param("{}", None, None, id="empty JSON object is valid"),
        pytest.param(
            "{not valid json",
            "Invalid value in DevSettings/CliAttributeOverrides: must be a valid JSON string.",
            FailureLevel.ERROR,
            id="malformed JSON throws error",
        ),
        pytest.param(
            '["cinc_version"]',
            "Invalid value in DevSettings/CliAttributeOverrides: must be a JSON object.",
            FailureLevel.ERROR,
            id="JSON array (not object) throws error",
        ),
        pytest.param(
            '"just a string"',
            "Invalid value in DevSettings/CliAttributeOverrides: must be a JSON object.",
            FailureLevel.ERROR,
            id="JSON scalar (not object) throws error",
        ),
    ],
)
def test_cli_attribute_overrides_validator(cli_attribute_overrides, expected_message, expected_failure_level):
    actual_failures = CliAttributeOverridesValidator().execute(cli_attribute_overrides=cli_attribute_overrides)
    assert_failure_messages(actual_failures, expected_message)
    if expected_failure_level:
        assert_failure_level(actual_failures, expected_failure_level)
