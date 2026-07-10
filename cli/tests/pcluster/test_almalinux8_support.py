# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions
# and limitations under the License.

from pathlib import Path

import pytest
import yaml
from assertpy import assert_that

from pcluster.constants import (
    CAPACITY_RESERVATION_OS_MAP,
    CR_PLATFORM_LINUX_UNIX,
    OS_MAPPING,
    OS_TO_IMAGE_NAME_PART_MAP,
    PRIVATE_OSES,
    SUPPORTED_OSES,
)


IMAGEBUILDER_RESOURCES = (
    Path(__file__).resolve().parents[2] / "src" / "pcluster" / "resources" / "imagebuilder"
)


def _component_commands(component_name):
    component = yaml.safe_load((IMAGEBUILDER_RESOURCES / component_name).read_text(encoding="utf-8"))
    commands = []
    for phase in component["phases"]:
        for step in phase["steps"]:
            inputs = step.get("inputs", {})
            if isinstance(inputs, dict):
                commands.extend(inputs.get("commands", []))
    return "\n".join(commands)


def test_almalinux8_configuration_contract():
    assert_that(SUPPORTED_OSES).contains("almalinux8")
    assert_that(PRIVATE_OSES).contains("almalinux8")
    assert_that(OS_MAPPING["almalinux8"]).is_equal_to({"user": "ec2-user"})
    assert_that(CAPACITY_RESERVATION_OS_MAP["almalinux8"]).is_equal_to(CR_PLATFORM_LINUX_UNIX)
    assert_that(OS_TO_IMAGE_NAME_PART_MAP["almalinux8"]).is_equal_to("almalinux8-hvm")


@pytest.mark.parametrize(
    "component_name",
    [
        "parallelcluster.yaml",
        "parallelcluster_tag.yaml",
        "parallelcluster_test.yaml",
        "update_and_reboot.yaml",
    ],
)
def test_imagebuilder_components_detect_almalinux8(component_name):
    commands = _component_commands(component_name)
    assert_that(commands).contains("almalinux")
    assert_that(commands).contains("almalinux8")


@pytest.mark.parametrize("component_name", ["parallelcluster.yaml", "update_and_reboot.yaml"])
def test_imagebuilder_components_preserve_almalinux_release_packages_during_kernel_lock(component_name):
    commands = _component_commands(component_name)
    assert_that(commands).contains("yum versionlock almalinux-release almalinux-repos")
    assert_that(commands).contains("yum versionlock delete almalinux-release almalinux-repos")
