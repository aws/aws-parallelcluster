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


DCV_CONNECT_SCRIPT = "/opt/parallelcluster/scripts/pcluster_dcv_connect.sh"


def get_supported_dcv_os():
    """Return a list of all the operating system supported by DCV."""
    return ["centos7", "ubuntu1804", "alinux2"]


def get_supported_dcv_partition():
    """Return a list of all the partition supported by DCV."""
    return ["aws", "aws-cn"]  # NICE DCV license bucket is not present in us-gov
