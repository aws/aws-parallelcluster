# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with
# the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

PCLUSTER_STACK_PREFIX = "parallelcluster-"
PCLUSTER_NAME_MAX_LENGTH = 60
PCLUSTER_NAME_REGEX = r"^([a-zA-Z][a-zA-Z0-9-]{0,%d})$"
PCLUSTER_ISSUES_LINK = "https://github.com/aws/aws-parallelcluster/issues"
CIDR_ALL_IPS = "0.0.0.0/0"
DEFAULT_ARCHITECTURE = "x86_64"
SUPPORTED_ARCHITECTURES = ["x86_64", "arm64"]
FSX_SSD_THROUGHPUT = [50, 100, 200]
FSX_HDD_THROUGHPUT = [12, 40]
SUPPORTED_OSS = ["alinux2", "ubuntu1804", "ubuntu2004", "centos7"]
