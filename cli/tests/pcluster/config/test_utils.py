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

from pcluster.utils import get_instance_vcpus
from tests.common import MockedBoto3Request


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.utils.boto3"


@pytest.mark.parametrize("valid_instance_type, expected_vcpus", [(True, 96), (False, -1)])
def test_get_instance_vcpus(boto3_stubber, valid_instance_type, expected_vcpus):
    instance_type = "g4dn.metal"
    mocked_requests = [
        MockedBoto3Request(
            method="describe_instance_types",
            response={
                "InstanceTypes": [{"InstanceType": "g4dn.metal", "VCpuInfo": {"DefaultVCpus": 96, "DefaultCores": 48}}]
            },
            expected_params={"InstanceTypes": [instance_type]},
            generate_error=not valid_instance_type,
        )
    ]

    boto3_stubber("ec2", mocked_requests)
    assert_that(get_instance_vcpus(instance_type)).is_equal_to(expected_vcpus)
