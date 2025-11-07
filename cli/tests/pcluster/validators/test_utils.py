# Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from pcluster.validators.utils import dig, is_boolean_string, str_to_bool


@pytest.mark.parametrize(
    "string_value, expected_result",
    [
        # Valid cases
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("false", False),
        ("False", False),
        ("FALSE", False),
        # Invalid cases
        ("yes", False),
        ("no", False),
        ("1", False),
        ("0", False),
        ("", False),
        (None, False),
    ],
)
def test_str_to_bool(string_value, expected_result):
    assert str_to_bool(string_value) == expected_result


@pytest.mark.parametrize(
    "value, expected_result",
    [
        # Valid cases
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("false", True),
        ("False", True),
        ("FALSE", True),
        (True, True),
        (False, True),
        # Invalid cases
        (None, False),
        ("", False),
        ("yes", False),
        ("no", False),
        ("1", False),
        ("0", False),
        (1, False),
        (0, False),
    ],
)
def test_is_boolean_string(value, expected_result):
    assert is_boolean_string(value) == expected_result


@pytest.mark.parametrize(
    "dictionary, keys, expected_result",
    [
        # Cases where value is found
        ({"a": {"b": {"c": "value"}}}, ("a", "b", "c"), "value"),
        ({"a": {"b": "value"}}, ("a", "b"), "value"),
        ({"a": "value"}, ("a",), "value"),
        ({"a": {"b": {"c": "value"}}}, ("a", "b"), {"c": "value"}),
        # Cases where value is not found
        ({"a": {"b": {"c": "value"}}}, ("a", "nonexistent"), None),
        ({"a": {"b": {"c": "value"}}}, ("nonexistent",), None),
        ({"a": {"b": {"c": "value"}}}, ("a", "b", "c", "d"), None),
        ({}, ("a",), None),
        (None, ("a",), None),
        ({"a": None}, ("a", "b"), None),
        ({"a": "not_dict"}, ("a", "b"), None),
        ({"a": {"b": None}}, ("a", "b", "c"), None),
    ],
)
def test_dig(dictionary, keys, expected_result):
    assert dig(dictionary, *keys) == expected_result
