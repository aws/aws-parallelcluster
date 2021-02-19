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
    CustomAction,
    Efa,
    Resource,
)
from pcluster.validators.cluster_validators import (
    DuplicateInstanceTypeValidator,
    EfaOsArchitectureValidator,
    EfaPlacementGroupValidator,
    EfaSecurityGroupValidator,
    EfaValidator,
    InstanceArchitectureCompatibilityValidator,
    SchedulerOsValidator,
)
from pcluster.validators.ec2_validators import InstanceTypeValidator


class SlurmComputeResource(BaseComputeResource):
    """Represent the Slurm Compute Resource."""

    def __init__(
        self, max_count: int = None, min_count: int = None, spot_price: float = None, efa: Efa = None, **kwargs
    ):
        super().__init__(**kwargs)
        self.max_count = Resource.init_param(max_count, default=10)
        self.min_count = Resource.init_param(min_count, default=0)
        self.spot_price = Resource.init_param(spot_price)
        self.efa = efa

    def _register_validators(self):
        self._add_validator(InstanceTypeValidator, instance_type=self.instance_type)
        if self.efa:
            self._add_validator(
                EfaValidator,
                instance_type=self.instance_type,
                efa_enabled=self.efa.enabled,
                gdr_support=self.efa.gdr_support,
            )


class SlurmQueue(BaseQueue):
    """Represent the Slurm Queue resource."""

    def __init__(
        self, compute_resources: List[SlurmComputeResource], custom_actions: List[CustomAction] = None, **kwargs
    ):
        super().__init__(**kwargs)
        self.compute_resources = compute_resources
        self.custom_actions = custom_actions

    def _register_validators(self):
        self._add_validator(
            DuplicateInstanceTypeValidator,
            instance_type_list=self.instance_type_list,
        )
        for compute_resource in self.compute_resources:
            if compute_resource.efa:
                self._add_validator(
                    EfaSecurityGroupValidator,
                    efa_enabled=compute_resource.efa,
                    security_groups=self.networking.security_groups,
                    additional_security_groups=self.networking.additional_security_groups,
                )
                if self.networking.placement_group:
                    self._add_validator(
                        EfaPlacementGroupValidator,
                        efa_enabled=compute_resource.efa,
                        placement_group_id=self.networking.placement_group.id,
                        placement_group_enabled=self.networking.placement_group.enabled,
                    )

    @property
    def instance_type_list(self):
        """Return the list of instance types associated to the Queue."""
        return [compute_resource.instance_type for compute_resource in self.compute_resources]


class Dns(Resource):
    """Represent the DNS settings."""

    def __init__(self, disable_managed_dns: bool = None, domain: str = None, hosted_zone_id: str = None):
        super().__init__()
        self.disable_managed_dns = Resource.init_param(disable_managed_dns, default=False)
        self.domain = Resource.init_param(domain)
        self.hosted_zone_id = Resource.init_param(hosted_zone_id)


class SlurmSettings(CommonSchedulingSettings):
    """Represent the Slurm settings."""

    def __init__(self, scaledown_idletime: int, dns: Dns = None):
        super().__init__(scaledown_idletime)
        self.dns = dns


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
        super()._register_validators()
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
