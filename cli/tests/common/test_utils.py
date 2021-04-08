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

from common.utils import get_url_scheme, parse_bucket_url, validate_json_format


@pytest.mark.parametrize(
    "data, expected_value",
    [
        ('{"cluster": {"scheduler_slots": "cores"}}', True),
        ('{"cluster"}: {"scheduler_slots": "cores"}}', False),
    ],
)
def test_validate_json_format(data, expected_value):
    assert_that(validate_json_format(data)).is_equal_to(expected_value)


@pytest.mark.parametrize(
    "url, expect_output",
    [
        ("https://test.s3.cn-north-1.amazonaws.com.cn/post_install.sh", "https"),
        (
            "s3://test/post_install.sh",
            "s3",
        ),
    ],
)
def test_get_url_scheme(url, expect_output):
    assert_that(get_url_scheme(url)).is_equal_to(expect_output)


@pytest.mark.parametrize(
    "url, expect_output",
    [
        (
            "s3://test/post_install.sh",
            {"bucket_name": "test", "object_key": "post_install.sh", "object_name": "post_install.sh"},
        ),
        (
            "s3://test/templates/3.0/post_install.sh",
            {
                "bucket_name": "test",
                "object_key": "templates/3.0/post_install.sh",
                "object_name": "post_install.sh",
            },
        ),
    ],
)
def test_parse_bucket_url(url, expect_output):
    assert_that(parse_bucket_url(url)).is_equal_to(expect_output)
