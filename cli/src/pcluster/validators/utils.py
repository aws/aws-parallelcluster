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
#
# This module contains all the classes representing the Resources objects.
# These objects are obtained from the configuration file through a conversion based on the Schema classes.
#
from typing import Any, Union

BOOLEAN_VALUES = ["true", "false"]


def get_bucket_name_from_s3_url(import_path):
    return import_path.split("/")[2]


def str_to_bool(string: str = None) -> bool:
    """Convert string to boolean value.

    Args:
        string: String to convert. Defaults to None.

    Returns:
        True if string is "true" (case-insensitive), False otherwise.
    """
    return str(string).lower() == "true"


def is_boolean_string(value: str) -> bool:
    """Check if value is a valid boolean string.

    Args:
        value: String value to check.

    Returns:
        True if value is "true" or "false" (case-insensitive), False otherwise.
    """
    return str(value).lower() in BOOLEAN_VALUES


def dig(dictionary: dict, *keys: str) -> Union[dict, None, Any]:
    """Navigate nested dictionary using key path.

    Args:
        dictionary: Dictionary to navigate.
        *keys: Sequence of keys to traverse.

    Returns:
        Value at the specified key path, or None if path doesn't exist.
    """
    if dictionary is None:
        return None
    value = dictionary
    for key in keys:
        if value is None or not isinstance(value, dict):
            return None
        value = value.get(key)
    return value
