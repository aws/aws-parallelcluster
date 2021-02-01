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


class Param:
    """Custom class to wrap a value and add more attributes."""

    def __init__(self, value, default=None, valid: bool = True):
        """
        Initialize param by adding internal attributes.

        Implied attribute is useful for distinguishing values implied vs specified by a user.
        """
        if value is None and default is not None:
            self.value = default
            self.implied = True
        else:
            self.value = value
            self.implied = False
        self.valid = valid


class DynamicParam:
    """Class to manage dynamic params that must be calculated at usage time."""

    def __init__(self, value_calculator):
        """Initialize dynamic param by saving the function to be used to retrieve the value."""
        self.__value_calculator = value_calculator

    @property
    def value(self):
        """Calculate and return the value."""
        return self.__value_calculator()
