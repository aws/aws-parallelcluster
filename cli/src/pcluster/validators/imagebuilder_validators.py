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

from pcluster import imagebuilder_utils
from pcluster.aws.aws_api import AWSApi
from pcluster.validators.common import FailureLevel, Validator


class AMIVolumeSizeValidator(Validator):
    """AMI root volume size validator."""

    def _validate(self, volume_size: int, image: str):
        """Validate the volume size is larger than base ami volume size."""
        ami_id = imagebuilder_utils.get_ami_id(image)
        ami_info = AWSApi.instance().ec2.describe_image(ami_id)
        min_volume_size = ami_info.volume_size
        if volume_size < min_volume_size:
            self._add_failure(
                "Root volume size {0} GB is less than the minimum required size {1} GB that equals parent ami "
                "volume size.".format(volume_size, min_volume_size),
                FailureLevel.ERROR,
            )


class ComponentsValidator(Validator):
    """Components number validator."""

    def _validate(self, components: list):
        """Validate the number of components is not greater than 15."""
        if components and len(components) > 15:
            self._add_failure(
                "Number of build components is {0}. "
                "It's not possible to specify more than 15 build components.".format(len(components)),
                FailureLevel.ERROR,
            )


class SecurityGroupsAndSubnetValidator(Validator):
    """Security Groups and Subnet validator."""

    def _validate(self, security_group_ids: list, subnet_id: str):
        """Validate security groups is required if subnet is specified."""
        if subnet_id:
            if not security_group_ids:
                self._add_failure(
                    "Subnet id {0} is specified, security groups is required.".format(subnet_id),
                    FailureLevel.ERROR,
                )


class RequireImdsV2Validator(Validator):
    """IMDSv2 enforcement validator."""

    def _validate(self, require_imds_v2):
        if not require_imds_v2:
            self._add_failure(
                "The current build image configuration does not disable IMDSv1, "
                "which we plan to disable by default in future versions. If you do "
                "not explicitly need to use IMDSv1 enforce IMDSv2 usage by setting the "
                "RequireImdsV2 configuration parameter to true (see documentation at: "
                "https://docs.aws.amazon.com/parallelcluster/latest/ug/Build-v3.html)",
                level=FailureLevel.INFO,
            )
