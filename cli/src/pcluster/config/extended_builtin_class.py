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

# Extend build-in classes to record if a value is implied.
# This is useful for distinguishing values implied vs specified by a user.
class MarkedInt(int):
    """Custom class to add more attributes to int."""

    def __new__(cls, number: int, implied: bool = True):
        """Create int object and add attributes."""
        obj = int.__new__(cls, number)
        obj.implied = implied
        return obj


class MarkedStr(str):
    """Custom class to add more attributes to str."""

    def __new__(cls, s: str, implied: bool = True):
        """Create str object and add attributes."""
        obj = str.__new__(cls, s)
        obj.implied = implied
        return obj


class MarkedBool(object):
    """
    Create bool object and add attributes.

    bool cannot be the base class. We have to write the class in another style.
    """

    def __init__(self, b: bool, implied: bool = True):
        """Initialize extended bool object."""
        self.b = b
        self.implied = implied

    def __bool__(self):
        """Bool operation depends on object attribute b."""
        return self.b
