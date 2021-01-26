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
# This module contains all the classes extended from Python built-in classes.
# By extending build-in classes, we can add custom attributes while keep all the behaviors of the super class.
#

# Mark all values. This is useful for distinguishing values implied vs specified by a user.
class MarkedValue:
    """Custom class to wrap a value and add more attributes."""

    def __init__(self, value, implied: bool = False, valid: bool = True):
        """Create MarkedValue object and add attributes."""
        self.value = value
        self.implied = implied
        self.valid = valid


def create_marked_value(value):
    """Create MarkedValue."""
    # if value is None:
    #    return None
    if isinstance(value, MarkedValue):
        # If the value is already MarkedValue, return it directly. This happens when a default value was assigned.
        return value
    else:
        return MarkedValue(value)


def create_default_value(value):
    """Create MarkedValue with implied == True."""
    return MarkedValue(value, implied=True)
