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

"""This module provides unit tests for the functions in the pcluster.commands module."""
import os

import pytest
from botocore.exceptions import UnStubbedResponseError

from pcluster.utils import get_instance_type
from tests.common import MockedBoto3Request


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.utils.boto3"


def test_cache(boto3_stubber):
    mocked_requests = [
        MockedBoto3Request(
            method="describe_instance_types",
            response={
                "InstanceTypes": [
                    {
                        "InstanceType": "t2.micro",
                        "VCpuInfo": {"DefaultVCpus": 96, "DefaultCores": 48, "DefaultThreadsPerCore": 2},
                        "NetworkInfo": {"EfaSupported": True},
                    }
                ]
            },
            expected_params={"InstanceTypes": ["t2.micro"]},
        )
    ]

    # First cache is disabled
    os.environ["PCLUSTER_CACHE_DISABLED"] = "yes"
    boto3_stubber("ec2", mocked_requests)

    # First call must be stubbed
    get_instance_type("t2.micro")

    # Second call must fail for missing stubber
    with pytest.raises(UnStubbedResponseError):
        get_instance_type("t2.micro")

    # Now cache is re-enabled
    del os.environ["PCLUSTER_CACHE_DISABLED"]

    # First call must be stubbed
    boto3_stubber("ec2", mocked_requests)
    get_instance_type("t2.micro")

    # Second call must be from cache
    get_instance_type("t2.micro")
