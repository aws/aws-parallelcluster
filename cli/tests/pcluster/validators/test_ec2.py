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
from assertpy import assert_that

from pcluster.validators.common import ConfigValidationError
from pcluster.validators.ec2 import InstanceTypeValidator


def _assert_validation_result(validator, failure_message, *validator_args):
    """Call the validator and check the result."""
    if failure_message:
        with pytest.raises(ConfigValidationError, match=failure_message):
            validator(*validator_args)
    else:
        assert_that(validator(*validator_args)).is_empty()


@pytest.mark.parametrize(
    "instance_type, failure_message", [("t2.micro", None), ("c4.xlarge", None), ("c55.xlarge", "is not supported")]
)
def test_instance_type_validator(mocker, instance_type, failure_message):
    mocker.patch(
        "pcluster.validators.ec2.Ec2Client.describe_instance_type_offerings", return_value=["t2.micro", "c4.xlarge"]
    )

    validator = InstanceTypeValidator(raise_on_error=True)
    _assert_validation_result(validator, failure_message, instance_type)
