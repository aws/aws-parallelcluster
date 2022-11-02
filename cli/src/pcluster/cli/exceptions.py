#!/usr/bin/env python3
# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not
# use this file except in compliance with the License. A copy of the License is
# located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or
# implied. See the License for the specific language governing permissions and
# limitations under the License.

import json


class CLIException(Exception):
    """Base CLI Exception class."""

    def __init__(self, data):
        self.data = data
        super().__init__()

    def __str__(self):
        return json.dumps(self.data, indent=2)


class APIOperationException(CLIException):
    """Thrown while calling API operations."""

    def __init__(self, data):
        super().__init__(data)


class ParameterException(CLIException):
    """Thrown for invalid parameters."""

    def __init__(self, data):
        super().__init__(data)
