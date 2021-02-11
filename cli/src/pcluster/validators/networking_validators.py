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
from typing import List

import boto3
from botocore.exceptions import ClientError

from pcluster.validators.common import FailureLevel, Validator


class SecurityGroupsValidator(Validator):
    """SubnetId validator."""

    def _validate(self, security_group_ids: List[str]):
        for sg_id in security_group_ids:
            try:
                boto3.client("ec2").describe_security_groups(GroupIds=[sg_id])
            except ClientError as e:
                self._add_failure.append(e.response.get("Error").get("Message"), FailureLevel.ERROR)
