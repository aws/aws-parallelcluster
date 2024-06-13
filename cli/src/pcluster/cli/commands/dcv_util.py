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

from pcluster.constants import SUPPORTED_OSES

UNSUPPORTED_OSES_FOR_DCV = ["alinux2023"]


def get_supported_dcv_os(architecture):
    """Return a list of all the operating system supported by DCV."""
    architectures_dict = {
        "x86_64": [os for os in SUPPORTED_OSES if os not in UNSUPPORTED_OSES_FOR_DCV],
        "arm64": ["alinux2", "centos7", "rhel8", "rocky8", "rhel9", "rocky9"],
    }
    return architectures_dict.get(architecture, [])
