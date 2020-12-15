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
# This module defines the storage classes representing the "live" objects in EC2.
#

from pcluster.config.cluster_config import EbsConfig, EfsConfig, FsxConfig


class Ebs:
    """Represent EBS storage object."""

    def __init__(self, config: EbsConfig):
        self.config = config
        self.mount_dir = self.config.mount_dir
        self.encrypted = self.config.encrypted
        self.id = self.config.id


class Efs:
    """Represent Fsx storage object."""

    def __init__(self, config: EfsConfig):
        self.config = config


class Fsx:
    """Represent Fsx storage object."""

    def __init__(self, config: FsxConfig):
        self.config = config
