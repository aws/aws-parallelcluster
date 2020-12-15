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
# This module defines the core classes: the cluster and related resources representing the "live" objects in EC2 or CFN.
#

from abc import ABC, abstractmethod

import yaml

from common.boto3.s3 import S3Client
from pcluster.config.cluster_config import ClusterConfig, HeadNodeConfig, SharedStorageType
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.storage import Ebs, Efs, Fsx


class HeadNode:
    """Represent the HeadNode object."""

    def __init__(self, config: HeadNodeConfig):
        self.config = config
        self.instance_type = config.instance_type


class Cluster(ABC):
    """Represent the Cluster object."""

    def __init__(self, region: str, name: str, config: ClusterConfig = None):
        self.region = region
        self.name = name
        self.config = config or self._load_config_from_s3()
        self.type = config.scheduling_config.scheduler
        self._init_common_components_from_config()
        self._init_from_config()

    @staticmethod
    def _load_config_from_s3():
        """Download saved config and convert Schema to Config object."""
        s3_bucket_name = "test"
        config_file = S3Client().download_file(s3_bucket_name)
        config_yaml = yaml.load(config_file, Loader=yaml.SafeLoader)
        return ClusterSchema().load(config_yaml)

    @abstractmethod
    def _init_from_config(self):
        pass

    def _init_common_components_from_config(self):
        """Initialize components common to all the cluster types from the config."""
        self.head_node = HeadNode(self.config.head_node_config)

        self.ebs_volumes = []
        self.fsx = None
        self.efs = None

        if self.config.shared_storage_list_config:
            for shared_storage_config in self.config.shared_storage_list_config:
                if shared_storage_config.type is SharedStorageType.EBS:
                    self.ebs_volumes.append(Ebs(shared_storage_config))
                if shared_storage_config.type is SharedStorageType.EFS:
                    self.efs = Efs(shared_storage_config)
                if shared_storage_config.type is SharedStorageType.FSX:
                    self.efs = Fsx(shared_storage_config)

    def create(self):
        """Generate template and instantiate stack."""
        pass

    @abstractmethod
    def update(self):
        """Update the cluster and related resources."""
        pass

    @abstractmethod
    def describe(self):
        """Return cluster information by checking internal resources."""
        pass

    @abstractmethod
    def stop(self):
        """Stop cluster related resources."""
        pass

    @abstractmethod
    def start(self):
        """Start cluster related resources."""
        pass


class SlurmCluster(Cluster):
    """."""

    def _init_from_config(self):
        self.head_node = HeadNode(self.config.head_node_config)
        # self.queues = ...
        pass

    def update(self):
        pass

    def describe(self):
        """Return cluster information by checking internal resources (e.g. HeadNode, Queues, etc)."""
        pass

    def stop(self):
        """Stop cluster related resources."""
        pass

    def start(self):
        """Start cluster related resources."""
        pass


class BatchCluster(Cluster):
    """."""

    def update(self):
        pass

    def describe(self):
        """Return cluster information by checking internal resources (e.g. CE, JobQueue, JobDefinition, etc)."""
        pass

    def stop(self):
        """Stop cluster related resources."""
        # TODO specific logic to manage Batch related resources (e.g. deactivate Compute environment)
        pass

    def start(self):
        """Start cluster related resources."""
        # TODO specific logic to manage Batch related resources (e.g. activate Compute environment)
        pass
