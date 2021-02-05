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
# This module contains all the classes representing the Resources objects.
# These objects are obtained from the configuration file through a conversion based on the Schema classes.
#
from typing import List

from pcluster.models.cluster import (
    BaseCluster,
    BaseComputeResource,
    BaseQueue,
    CommonSchedulingSettings,
    Efa,
    QueueNetworking,
    Resource,
    Storage,
)
from pcluster.models.common import Param
from pcluster.validators.cluster_validators import (
    EfaOsArchitectureValidator,
    InstanceArchitectureCompatibilityValidator,
    SchedulerOsValidator,
)
from pcluster.validators.ec2_validators import InstanceTypeValidator


class SlurmComputeResource(BaseComputeResource):
    """Represent the Slurm Compute Resource."""

    def __init__(
        self,
        instance_type: str,
        max_count: int = None,
        min_count: int = None,
        spot_price: float = None,
        allocation_strategy: str = None,
        simultaneous_multithreading: bool = None,
        efa: Efa = None,
    ):
        super().__init__(allocation_strategy, simultaneous_multithreading, efa)
        self.instance_type = Param(instance_type)
        self.max_count = Param(max_count, default=10)
        self.min_count = Param(min_count, default=0)
        self.spot_price = Param(spot_price)
        self._add_validator(InstanceTypeValidator, instance_type=self.instance_type)


class SlurmQueue(BaseQueue):
    """Represent the Slurm Queue resource."""

    def __init__(
        self,
        name: str,
        networking: QueueNetworking,
        compute_resources: List[SlurmComputeResource],
        storage: Storage = None,
        compute_type: str = None,
    ):
        super().__init__(name, networking, storage, compute_type)
        self.compute_resources = compute_resources


class SlurmSettings(CommonSchedulingSettings):
    """Represent the Slurm settings."""

    def __init__(self, scaledown_idletime: int):
        super().__init__(scaledown_idletime)
        # self.dns = dns


class SlurmScheduling(Resource):
    """Represent a slurm Scheduling resource."""

    def __init__(self, queues: List[SlurmQueue], settings: SlurmSettings = None):
        super().__init__()
        self.scheduler = "slurm"
        self.queues = queues
        self.settings = settings


class SlurmCluster(BaseCluster):
    """Represent the full Slurm Cluster configuration."""

    def __init__(self, scheduling: SlurmScheduling, **kwargs):
        super().__init__(**kwargs)
        self.scheduling = scheduling

    def _register_validators(self):
        self._add_validator(SchedulerOsValidator, scheduler=self.scheduling.scheduler, os=self.image.os)

        for queue in self.scheduling.queues:
            for compute_resource in queue.compute_resources:
                self._add_validator(
                    InstanceArchitectureCompatibilityValidator,
                    instance_type=compute_resource.instance_type,
                    architecture=self.head_node.architecture,
                )
                if compute_resource.efa:
                    self._add_validator(
                        EfaOsArchitectureValidator,
                        priority=9,
                        efa_enabled=compute_resource.efa.enabled,
                        os=self.image.os,
                        architecture=self.head_node.architecture,
                    )
