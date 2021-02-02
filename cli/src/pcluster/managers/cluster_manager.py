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
# This module defines the classes to manage the "live" objects in EC2 or CFN.
#

from abc import ABC, abstractmethod

import yaml

from pcluster.models.cluster import BaseCluster
from pcluster.schemas.cluster_schema import ClusterSchema


class ClusterManager(ABC):
    """Represent the Cluster Manager."""

    def __init__(self, cluster: BaseCluster = None):
        self.cluster = cluster or self._load_cluster_from_s3()

    @staticmethod
    def _load_cluster_from_s3():
        """Download saved config and convert Schema to Config object."""
        config_file = "test"
        # FIXME config_file = S3Client().download_file(s3_bucket_name)
        config_yaml = yaml.load(config_file, Loader=yaml.SafeLoader)
        return ClusterSchema().load(config_yaml)

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


class SlurmClusterManager(ClusterManager):
    """Represent a Slurm cluster manager."""

    def update(self):
        """Update the cluster and related resources."""
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


class BatchClusterManager(ClusterManager):
    """Represent a Batch cluster manager."""

    def update(self):
        """Update the cluster and related resources."""
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
