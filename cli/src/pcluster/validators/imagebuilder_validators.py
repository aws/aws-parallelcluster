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

from common import imagebuilder_utils
from common.boto3.ec2 import Ec2Client
from pcluster.validators.common import FailureLevel, Validator


class AMIVolumeSizeValidator(Validator):
    """AMI root volume size validator."""

    def _validate(self, volume_size: int, image: str, pcluster_reserved_volume_size: int):
        """Validate the volume size is larger than base ami volume size."""
        ami_id = imagebuilder_utils.get_ami_id(image)
        ami_info = Ec2Client().describe_image(ami_id)
        base_ami_volume_size = ami_info.get("BlockDeviceMappings")[0].get("Ebs").get("VolumeSize")
        min_volume_size = base_ami_volume_size + pcluster_reserved_volume_size
        if volume_size < min_volume_size:
            self._add_failure(
                "Root volume size {0} GB is less than the minimum required size {1} GB that equals base ami {2} GB "
                "plus size 15 GB to allow PCluster software stack installation.".format(
                    volume_size, min_volume_size, base_ami_volume_size
                ),
                FailureLevel.ERROR,
            )
