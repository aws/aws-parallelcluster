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

from pcluster.validators.validator_ec2 import InstanceTypeValidator
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "instance_type, expected_message", [("t2.micro", None), ("c4.xlarge", None), ("c5.xlarge", "is not supported")]
)
def test_instance_type_validator(mocker, instance_type, expected_message):

    mocker.patch("pcluster.validators.validator_ec2.Ec2Client.__init__", return_value=None)
    mocker.patch(
        "pcluster.validators.validator_ec2.Ec2Client.describe_instance_type_offerings",
        return_value=["t2.micro", "c4.xlarge"],
    )

    actual_failures = InstanceTypeValidator()(instance_type)
    assert_failure_messages(actual_failures, expected_message)
