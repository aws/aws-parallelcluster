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

from pcluster.config.cluster_config import S3Access


@pytest.mark.parametrize(
    "bucket_name, key_name, expected_result",
    [
        ("FakeBucketName", None, ["FakeBucketName", "FakeBucketName/*"]),
        ("FakeBucketName", "FakeKey", ["FakeBucketName/FakeKey"]),
    ],
)
def test_s3_access_resources(bucket_name, key_name, expected_result):
    s3_access = S3Access(bucket_name, key_name)
    resources = s3_access.resource_regex
    assert_that(set(resources)).is_equal_to(set(expected_result))
