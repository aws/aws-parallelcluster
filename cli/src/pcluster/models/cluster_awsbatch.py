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
    QueueNetworking,
    Resource,
    Storage,
)
from pcluster.models.common import Param
from pcluster.validators.awsbatch_validators import (
    AwsbatchComputeInstanceTypeValidator,
    AwsbatchInstancesArchitectureCompatibilityValidator,
    AwsbatchRegionValidator,
)
from pcluster.validators.cluster_validators import EfaOsArchitectureValidator, SchedulerOsValidator


class AwsbatchComputeResource(BaseComputeResource):
    """Represent the Awsbatch Compute Resource."""

    def __init__(
        self,
        instance_type: str,
        max_vcpus: int = None,
        min_vcpus: int = None,
        desired_vcpus: int = None,
        spot_bid_percentage: float = None,
        allocation_strategy: str = None,
        simultaneous_multithreading: bool = None,
    ):
        super().__init__(allocation_strategy, simultaneous_multithreading)
        self.instance_type = instance_type
        self.max_vcpus = Param(max_vcpus, default=10)
        self.min_vcpus = Param(min_vcpus, default=0)
        self.desired_vcpus = Param(desired_vcpus, default=0)
        self.spot_bid_percentage = spot_bid_percentage

    def _register_validators(self):
        self._add_validator(
            AwsbatchComputeInstanceTypeValidator, instance_types=self.instance_type, max_vcpus=self.max_vcpus
        )


class AwsbatchQueue(BaseQueue):
    """Represent the Awsbatch Queue resource."""

    def __init__(
        self,
        name: str,
        networking: QueueNetworking,
        compute_resources: List[AwsbatchComputeResource],
        storage: Storage = None,
        compute_type: str = None,
    ):
        super().__init__(name, networking, storage, compute_type)
        self.compute_resources = compute_resources


class AwsbatchScheduling(Resource):
    """Represent a Awsbatch Scheduling resource."""

    def __init__(self, queues: List[AwsbatchQueue], settings: CommonSchedulingSettings = None):
        super().__init__()
        self.scheduler = "awsbatch"
        self.queues = queues
        self.settings = settings


class AwsbatchCluster(BaseCluster):
    """Represent the full Awsbatch Cluster configuration."""

    def __init__(self, scheduling: AwsbatchScheduling, **kwargs):
        super().__init__(**kwargs)
        self.scheduling = scheduling

    def _register_validators(self):
        self._add_validator(AwsbatchRegionValidator, region=self.region)
        self._add_validator(SchedulerOsValidator, scheduler=self.scheduling.scheduler, os=self.image.os)

        for queue in self.scheduling.queues:
            for compute_resource in queue.compute_resources:
                self._add_validator(
                    AwsbatchInstancesArchitectureCompatibilityValidator,
                    instance_types=compute_resource.instance_type,
                    architecture=self.head_node.architecture,
                )
                if compute_resource.efa:
                    self._add_validator(
                        EfaOsArchitectureValidator,
                        efa_enabled=compute_resource.efa.enabled,
                        os=self.image.os,
                        architecture=self.head_node.architecture,
                    )
