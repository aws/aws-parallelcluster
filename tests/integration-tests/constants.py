# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with
# the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

OS_TO_ROOT_VOLUME_DEVICE = {
    "centos7": "/dev/sda1",
    "alinux2": "/dev/xvda",
    "ubuntu1804": "/dev/sda1",
    "ubuntu2004": "/dev/sda1",
}

SCHEDULERS_SUPPORTING_IMDS_SECURED = ["slurm"]
