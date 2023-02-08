# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# This series of imports and functions is to move parallelcluster functionality
# to the module level.
# flake8: noqa
from pcluster.lib import lib

# Dynamically add pcluster functions to the pcluster module
# pylint: disable=protected-access
lib._add_functions(lib._load_model(), lib)

# Now import the additional functions into this module.
# pylint: disable=wrong-import-position
from pcluster.lib.lib import *
