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

from pcluster.validators.scheduler_plugin_validators import (
    SchedulerPluginOsArchitectureValidator,
    SchedulerPluginRegionValidator,
    SudoPrivilegesValidator,
    SupportedVersionsValidator,
)
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "grant_sudo_privileges, requires_sudo_privileges, expected_message",
    [
        (True, None, None),
        (True, True, None),
        (True, False, None),
        (False, None, None),
        (
            None,
            True,
            "The scheduler plugin required sudo privileges through RequiresSudoPrivileges=true "
            "but these privileges were not granted because GrantSudoPrivileges was not set or set to false.",
        ),
        (
            False,
            True,
            "The scheduler plugin required sudo privileges through RequiresSudoPrivileges=true "
            "but these privileges were not granted because GrantSudoPrivileges was not set or set to false.",
        ),
    ],
)
def test_sudo_privileges_validator(grant_sudo_privileges, requires_sudo_privileges, expected_message):
    actual_failures = SudoPrivilegesValidator().execute(grant_sudo_privileges, requires_sudo_privileges)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "os, architecture, supported_x86, supported_arm64, expected_message",
    [
        (
            "alinux2",
            "x86_64",
            ["alinux2", "centos7", "ubuntu1804", "ubuntu2004"],
            ["alinux2", "centos7", "ubuntu1804", "ubuntu2004"],
            None,
        ),
        (
            "centos7",
            "arm64",
            ["alinux2", "centos7", "ubuntu1804", "ubuntu2004"],
            ["alinux2", "centos7", "ubuntu1804", "ubuntu2004"],
            None,
        ),
        (
            "alinux2",
            "x86_64",
            ["centos7", "ubuntu1804", "ubuntu2004"],
            ["alinux2", "ubuntu1804", "ubuntu2004"],
            "The scheduler plugin supports the OSs ['centos7', 'ubuntu1804', 'ubuntu2004'] for architecture x86_64, "
            "none of which are compatible with the configured OS (alinux2) and the architecture supported by the head "
            "node instance type (x86_64).",
        ),
        (
            "ubuntu1804",
            "arm64",
            ["ubuntu1804"],
            ["ubuntu2004"],
            "The scheduler plugin supports the OSs ['ubuntu2004'] for architecture arm64, none of which are "
            "compatible with the configured OS (ubuntu1804) and the architecture supported by the head node instance "
            "type (arm64).",
        ),
    ],
)
def test_scheduler_plugin_os_architecture_validator(os, architecture, supported_x86, supported_arm64, expected_message):
    actual_failures = SchedulerPluginOsArchitectureValidator().execute(os, architecture, supported_x86, supported_arm64)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "region, supported_regions, expected_message",
    [
        (
            "us-east-1",
            ["cn-north-1", "us-east-1"],
            None,
        ),
        (
            "us-west-1",
            ["cn-north-1", "us-east-1", "eu-west-1"],
            "The specified region us-west-1 is not supported by the scheduler plugin. Supported regions are",
        ),
        (
            "us-east-1",
            None,
            None,
        ),
    ],
)
def test_scheduler_plugin_region_validator(region, supported_regions, expected_message):
    actual_failures = SchedulerPluginRegionValidator().execute(region, supported_regions)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "installed_version, supported_versions, expected_message",
    [
        (
            "3.0.0",
            "3.0.0",
            None,
        ),
        (
            "3.0.0",
            "3.0.0,3.0.1",
            None,
        ),
        (
            "3.0.0b",
            "3.0.1,     3.0.0b",
            None,
        ),
        (
            "3.0.2",
            ">=3.0.1b1, <=3.1.0",
            None,
        ),
        (
            "3.0.0a1",
            ">=3.0.1b1, <=3.1.0",
            "The installed version 3.0.0a1 is not supported by the scheduler plugin. Supported versions are: "
            ">=3.0.1b1, <=3.1.0.",
        ),
        (
            "3.1.0",
            ">=2.9.0, <=3.1.1",
            None,
        ),
        (
            "3.1.0b1",
            ">=2.9.0, <=3.4.0",
            None,
        ),
        (
            "2.8.0",
            ">=2.9.0, <=3.1.1",
            "The installed version 2.8.0 is not supported by the scheduler plugin. Supported versions are: "
            ">=2.9.0, <=3.1.1.",
        ),
        (
            "2.8.0",
            ">=2.9.0, <=3.1.1, <=3.2.0, >=2.8.0",
            "The installed version 2.8.0 is not supported by the scheduler plugin. Supported versions are: "
            ">=2.9.0, <=3.1.1, <=3.2.0, >=2.8.0.",
        ),
        (
            "3.1.1",
            "<2.9.0, >3.1.1",
            "The installed version 3.1.1 is not supported by the scheduler plugin. Supported versions are: "
            "<2.9.0, >3.1.1.",
        ),
        (
            "3.1.1",
            "3.0.0, >=3.1.1",
            "Unable to parse SupportedParallelClusterVersions 3.0.0, >=3.1.1 in the scheduler plugin",
        ),
    ],
)
def test_supported_versions_validator(installed_version, supported_versions, expected_message):
    actual_failures = SupportedVersionsValidator().execute(installed_version, supported_versions)
    assert_failure_messages(actual_failures, expected_message)
