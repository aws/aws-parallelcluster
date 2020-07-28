# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from pcluster.config.resource_map import ResourceMap


def test_resource_map():
    resource_map = ResourceMap()

    # Store method cannot be called before alloc
    with pytest.raises(Exception):
        resource_map.store("test", ["a", "b", "c", "d"])

    resource_map.alloc("test", 4)
    resource_map.store("test", ["a", "b", "c", "d"])

    # A different order of values should not impact on the existing resources
    resource_map.store("test", ["b", "a", "d", "c"])
    assert_that(resource_map.resources("test")).is_equal_to(["a", "b", "c", "d"])

    # Removing resources should leave remaining ones at their positions
    resource_map.store("test", ["c", "b"])
    assert_that(resource_map.resources("test")).is_equal_to([None, "b", "c", None])

    # New resources should take first available slots
    resource_map.store("test", ["c", "b", "d", "a"])
    assert_that(resource_map.resources("test")).is_equal_to(["d", "b", "c", "a"])

    # Passing an empty array should clear all resources
    resource_map.store("test", [])
    assert_that(resource_map.resources("test")).is_equal_to([None, None, None, None])

    # Corner case: all empty resources before the one to store
    resource_map.store("test", ["a", "b", "c", "d"])
    resource_map.store("test", ["d"])
    assert_that(resource_map.resources("test")).is_equal_to([None, None, None, "d"])
    resource_map.store("test", ["d"])
    assert_that(resource_map.resources("test")).is_equal_to([None, None, None, "d"])

    # Adding more resources than max allowed should raise an exception
    with pytest.raises(Exception):
        resource_map.store("test", ["a", "b", "c", "d", "e"])
