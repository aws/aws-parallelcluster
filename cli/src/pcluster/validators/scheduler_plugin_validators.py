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
import operator
import re
from collections import namedtuple

from pkg_resources import packaging

from pcluster.utils import get_attr
from pcluster.validators.common import FailureLevel, Validator

USER_NAME_REGEX = r"^[a-z_]([a-z0-9_-]{0,31}|[a-z0-9_-]{0,30}\$)$"


class SudoPrivilegesValidator(Validator):
    """Sudo Privileges Validator."""

    def _validate(self, grant_sudo_privileges: bool, requires_sudo_privileges: bool):
        if requires_sudo_privileges and not grant_sudo_privileges:
            self._add_failure(
                "The scheduler plugin required sudo privileges through RequiresSudoPrivileges=true "
                "but these privileges were not granted because GrantSudoPrivileges was not set or set to false.",
                FailureLevel.ERROR,
            )


class GrantSudoPrivilegesValidator(Validator):
    """Verify SystemUsers does not have SudoerConfiguration set when GrantSudoPrivileges is true."""

    def _validate(self, grant_sudo_privileges: bool, system_users):
        if not grant_sudo_privileges and system_users:
            sudoer_configuration = [
                get_attr(user, "sudoer_configuration")
                for user in system_users
                if get_attr(user, "sudoer_configuration")
            ]
            if sudoer_configuration:
                self._add_failure(
                    "The used scheduler plugin requires the creation of SystemUsers with sudo access. To grant such "
                    "rights please set GrantSudoPrivileges to true.",
                    FailureLevel.ERROR,
                )


class SchedulerPluginOsArchitectureValidator(Validator):
    """Verify that head node architecture and os combination is supported by the scheduler plugin."""

    def _validate(self, os, architecture: str, supported_x86, supported_arm64):
        oss_and_supported_architectures_mapping = {"x86_64": supported_x86, "arm64": supported_arm64}
        supported_oss = oss_and_supported_architectures_mapping.get(architecture)
        if os not in supported_oss:
            self._add_failure(
                "The scheduler plugin supports the OSs {0} for architecture {1}, none of which are "
                "compatible with the configured OS ({2}) and the architecture supported by the head node instance "
                "type ({1}).".format(supported_oss, architecture, os),
                FailureLevel.ERROR,
            )


class SchedulerPluginRegionValidator(Validator):
    """Verify that the region is supported by the scheduler plugin."""

    def _validate(self, region, supported_regions):
        if supported_regions and region not in supported_regions:
            self._add_failure(
                "The specified region {0} is not supported by the scheduler plugin. "
                "Supported regions are: {1}.".format(region, supported_regions),
                FailureLevel.ERROR,
            )


class SupportedVersionsValidator(Validator):
    """
    Validate if the installed ParallelCluster Version is supported by the scheduler plugin.

    The supported formats for SupportedParallelClusterVersions is either a string contains list of versions or a range.
    Example: "3.0.0, 3.0.1" or ">=3.1.0, <=3.1.0"
    """

    def _validate(self, installed_version, supported_versions_string):
        if supported_versions_string:
            supported_versions_list = [version.strip() for version in supported_versions_string.split(",")]
            if any(x in supported_versions_string for x in [">", "<"]):  # Input string is a range
                self._check_version_in_range(installed_version, supported_versions_list, supported_versions_string)
            elif installed_version not in supported_versions_list:  # Input string is a list of versions
                self._add_failure(
                    "The installed version {0} is not supported by the scheduler plugin ({1}).".format(
                        installed_version, supported_versions_string
                    ),
                    FailureLevel.ERROR,
                )

    def _check_version_in_range(self, installed_version, supported_versions_list, supported_versions_string):
        """Check if the installed version is inside the supported versions range."""
        CliRequirement = namedtuple("Requirement", "operator version")
        comparison_operators = {
            "<": operator.lt,
            "<=": operator.le,
            "==": operator.eq,
            "!=": operator.ne,
            ">=": operator.ge,
            ">": operator.gt,
        }
        requirements = []
        for version in supported_versions_list:
            try:
                match = re.search(r"^([<>=!]+)([\d.]+)", version)
                requirements.append(CliRequirement(operator=match.group(1), version=match.group(2)))
            except Exception as e:
                self._add_failure(
                    "Unable to parse SupportedParallelClusterVersions {0} in the scheduler plugin: {1}. "
                    "The input of SupportedParallelClusterVersions can either contain multiple versions"
                    "(e.g., '3.0.0, 3.0.1') or a version range(e.g., '>=3.0.1, <3.4.0')".format(
                        supported_versions_string, e
                    ),
                    FailureLevel.ERROR,
                )
        for req in requirements:
            if not comparison_operators[req.operator](
                packaging.version.parse(installed_version),
                packaging.version.parse(req.version),
            ):
                self._add_failure(
                    "The installed version {0} is not supported by the scheduler plugin. Supported versions are: "
                    "{1}.".format(installed_version, supported_versions_string),
                    FailureLevel.ERROR,
                )


class UserNameValidator(Validator):
    """Validate queue name length and format."""

    def _validate(self, user_name):
        match = re.match(USER_NAME_REGEX, user_name)
        if not match:
            self._add_failure(
                (
                    f"Invalid SystemUsers name '{user_name}'. SystemUsers name must match the following pattern: "
                    f"{USER_NAME_REGEX}"
                ),
                FailureLevel.ERROR,
            )


class PluginInterfaceVersionValidator(Validator):
    """Check if PluginInterfaceVersion is supported."""

    def _validate(self, plugin_version, support_version_low_range, support_version_high_range):
        if not support_version_low_range <= packaging.version.parse(plugin_version) <= support_version_high_range:
            error_message = f"The PluginInterfaceVersion '{plugin_version}' is not supported."
            if support_version_low_range == support_version_high_range:
                error_message += f" Supported version is '{support_version_high_range}'."
            else:
                error_message += (
                    f" Supported versions are '>={support_version_low_range}, <= {support_version_high_range}'."
                )
            self._add_failure(error_message, FailureLevel.ERROR)
