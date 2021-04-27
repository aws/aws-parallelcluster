#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import pytest
from assertpy import assert_that

from pcluster.api.errors import BadRequestException
from pcluster.api.validators import validate_region


@pytest.mark.parametrize(
    "region, error",
    [
        ("eu-west-1", None),
        ("eu-west-", "invalid or unsupported region"),
        (None, "region needs to be set"),
    ],
)
class TestValidateRegion:
    def test_validate_region_query(self, region, error):
        @validate_region()
        def _decorated_func(region):
            pass

        if error:
            with pytest.raises(BadRequestException) as e:
                _decorated_func(region=region)
            assert_that(str(e.value.content)).contains(error)
        else:
            _decorated_func(region=region)

    def test_validate_region_body(self, region, error, client):
        client.post(json={"region": region})

        @validate_region(is_query_string_arg=False)
        def _decorated_func():
            pass

        if error:
            with pytest.raises(BadRequestException) as e:
                _decorated_func()
            assert_that(str(e.value.content)).contains(error)
        else:
            _decorated_func()

    def test_validate_region_env(self, region, error, set_env, unset_env):
        @validate_region()
        def _decorated_func():
            pass

        if region:
            set_env("AWS_DEFAULT_REGION", region)
        else:
            unset_env("AWS_DEFAULT_REGION")
        if error:
            with pytest.raises(BadRequestException) as e:
                _decorated_func()
            assert_that(str(e.value.content)).contains(error)
        else:
            _decorated_func()
