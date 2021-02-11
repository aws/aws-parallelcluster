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

from pcluster.models.common import Resource


@pytest.mark.parametrize(
    "value, default, expected_value, expected_implied",
    [
        ("abc", "default_value", "abc", False),
        (None, "default_value", "default_value", True),
        (5, 10, 5, False),
        (None, 10, 10, True),
    ],
)
def test_resource_params(value, default, expected_value, expected_implied):
    class TestBaseBaseResource(Resource):
        def __init__(self):
            super().__init__()

    class TestBaseResource(TestBaseBaseResource):
        def __init__(self):
            super().__init__()

    class TestResource(TestBaseResource):
        def __init__(self):
            super().__init__()
            self.test_attr = Resource.init_param(value=value, default=default)

    test_resource = TestResource()
    assert_that(test_resource.test_attr).is_equal_to(expected_value)
    assert_that(test_resource.is_implied("test_attr")).is_equal_to(expected_implied)

    param = test_resource.get_param("test_attr")
    assert_that(param).is_not_none()
    assert_that(param.value).is_equal_to(expected_value)
    assert_that(param.default).is_equal_to(default)

    test_resource.test_attr = "new_value"
    assert_that(test_resource.is_implied("test_attr")).is_false()

    param = test_resource.get_param("test_attr")
    assert_that(param).is_not_none()
    assert_that(param.value).is_equal_to("new_value")
    assert_that(param.default).is_equal_to(default)
