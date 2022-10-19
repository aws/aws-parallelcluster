# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from enum import Enum
from typing import Callable, Dict

from pcluster.aws.aws_resources import InstanceTypeInfo
from pcluster.config import cluster_config
from pcluster.validators.common import FailureLevel, Validator


class _FlexibleInstanceTypesValidatorMixin:
    def validate_property_homogeneity(
        self,
        instance_types_info: Dict[str, InstanceTypeInfo],
        property_callback: Callable,
        failure_message_callback: Callable[[Dict[str, int]], str],  # args: {instance_type: value, ...}
        failure_level: FailureLevel = FailureLevel.ERROR,
    ):
        """Check if the instance_types have the same property (CPU count, GPU count etc)."""
        instance_type_info_list = list(instance_types_info.values())

        instance_property, instance_type = None, None
        for instance_type_info in instance_type_info_list:
            current_instance_property = property_callback(instance_type_info)
            current_instance_type = instance_type_info.instance_type()
            if instance_property is not None and instance_property != current_instance_property:
                mismatching_values = {
                    instance_type: instance_property,
                    current_instance_type: current_instance_property,
                }
                self._add_failure(failure_message_callback(mismatching_values), failure_level)
                break
            instance_property = current_instance_property
            instance_type = current_instance_type


class InstancesCPUValidator(Validator, _FlexibleInstanceTypesValidatorMixin):
    """Confirm CPU requirements for Flexible Instance Types."""

    def _validate(
        self,
        compute_resource_name: str,
        instance_types_info: Dict[str, InstanceTypeInfo],
        disable_simultaneous_multithreading: bool,
        **kwargs,
    ):
        """Check if CPU requirements are met.

        Instance types should have the same number of CPUs or same number of Cores if Simultaneous Multithreading
        is disabled.
        """
        if disable_simultaneous_multithreading:
            self.validate_property_homogeneity(
                instance_types_info=instance_types_info,
                property_callback=lambda instance_type_info: instance_type_info.cores_count(),
                failure_message_callback=lambda heterogeneous_values: f"Instance types listed under Compute Resource "
                f"{compute_resource_name} must have the same number of CPU cores when Simultaneous Multithreading is "
                f"disabled ({heterogeneous_values}).",
            )
        else:
            self.validate_property_homogeneity(
                instance_types_info=instance_types_info,
                property_callback=lambda instance_type_info: instance_type_info.vcpus_count(),
                failure_message_callback=lambda heterogeneous_values: f"Instance types listed under Compute Resource "
                f"{compute_resource_name} must have the same number of vCPUs ({heterogeneous_values}).",
            )


class InstancesAcceleratorsValidator(Validator, _FlexibleInstanceTypesValidatorMixin):
    """Confirm Accelerator requirements for Flexible Instance Types."""

    def _validate(
        self,
        compute_resource_name: str,
        instance_types_info: Dict[str, InstanceTypeInfo],
        **kwargs,
    ):
        """Check if Accelerator requirements are met.

        Instance Types should have the same number of accelerators.
        """
        self.validate_property_homogeneity(
            instance_types_info=instance_types_info,
            property_callback=lambda instance_type_info: instance_type_info.gpu_count(),
            failure_message_callback=lambda heterogeneous_values: f"Instance types listed under Compute Resource "
            f"{compute_resource_name} must have the same number of GPUs ({heterogeneous_values}).",
        )
        self.validate_property_homogeneity(
            instance_types_info=instance_types_info,
            property_callback=lambda instance_type_info: instance_type_info.inference_accelerator_count(),
            failure_message_callback=lambda heterogeneous_values: f"Instance types listed under Compute Resource "
            f"{compute_resource_name} must have the same number of Inference Accelerators ({heterogeneous_values}).",
        )

        # Instance Types should have the same accelerator manufacturer
        self.validate_property_homogeneity(
            instance_types_info=instance_types_info,
            property_callback=lambda instance_type_info: instance_type_info.gpu_manufacturer(),
            failure_message_callback=lambda heterogeneous_values: f"Instance types listed under Compute Resource "
            f"{compute_resource_name} must have the same GPU manufacturer ({heterogeneous_values}).",
        )

        self.validate_property_homogeneity(
            instance_types_info=instance_types_info,
            property_callback=lambda instance_type_info: instance_type_info.inference_accelerator_manufacturer(),
            failure_message_callback=lambda heterogeneous_values: f"Instance types listed under Compute Resource "
            f"{compute_resource_name} must have the same inference accelerator manufacturer ({heterogeneous_values}).",
        )


class InstancesEFAValidator(Validator, _FlexibleInstanceTypesValidatorMixin):
    """Validate EFA requirements for Flexible Instance Types."""

    def _validate(
        self,
        compute_resource_name: str,
        instance_types_info: Dict[str, InstanceTypeInfo],
        efa_enabled: bool,
        **kwargs,
    ):
        """Check if EFA requirements are met.

        Validation Failure is expected if EFA is ENABLED and at least one instance type defined in the compute resource
        DOES NOT support EFA.
        """
        if efa_enabled:
            instance_types_without_efa_support = {
                instance_type_name
                for instance_type_name, instance_type_info in instance_types_info.items()
                if not instance_type_info.is_efa_supported()
            }

            # If ALL the instance types have EFA support, `instance_types_without_efa_support` should be empty
            # --> No failure expected
            # If SOME or ALL the instance types DO NOT have EFA support, `instance_types_without_efa_support` should
            # contain instance types--> Validation Failure expected
            if instance_types_without_efa_support:
                self._add_failure(
                    (
                        "Instance type(s) ({0}) do not support EFA and cannot be launched when EFA is enabled in "
                        "Compute Resource: {1}.".format(
                            ",".join(sorted(instance_types_without_efa_support)),
                            compute_resource_name,
                        )
                    ),
                    FailureLevel.ERROR,
                )
        else:
            instance_types_with_efa_support = {
                instance_type_name
                for instance_type_name, instance_type_info in instance_types_info.items()
                if instance_type_info.is_efa_supported()
            }
            if instance_types_with_efa_support:
                self._add_failure(
                    (
                        "The EC2 instance type(s) selected ({0}) for the Compute Resource {1} support enhanced "
                        "networking capabilities using Elastic Fabric Adapter (EFA). EFA enables you to run "
                        "applications requiring high levels of inter-node communications at scale on AWS at no "
                        "additional charge. You can update the cluster's configuration to enable EFA ("
                        "https://docs.aws.amazon.com/parallelcluster/latest/ug/efa-v3.html).".format(
                            ",".join(sorted(instance_types_with_efa_support)),
                            compute_resource_name,
                        )
                    ),
                    FailureLevel.WARNING,
                )


class InstancesNetworkingValidator(Validator, _FlexibleInstanceTypesValidatorMixin):
    """Confirm Networking requirements for Flexible Instance Types."""

    def _validate(
        self,
        queue_name: str,
        compute_resource_name: str,
        instance_types_info: Dict[str, InstanceTypeInfo],
        placement_group_enabled: bool,
        **kwargs,
    ):
        """Validate that the lowest value for the MaximumNetworkInterfaceCards among the Instance Types is used.

        Each instance type has a maximum number of Network Interface Cards. When the instance types in the  list
        have a varying number of 'maximum network interface cards', the smallest one is used  in the  launch template.
        """
        unique_maximum_nic_counts = {
            instance_type_info.max_network_interface_count()
            for instance_type_name, instance_type_info in instance_types_info.items()
        }

        if len(unique_maximum_nic_counts) > 1:
            lowest_nic_count = min(unique_maximum_nic_counts)
            highest_nic_count = max(unique_maximum_nic_counts)
            self._add_failure(
                f"Compute Resource {compute_resource_name} has instance types with varying numbers of network cards ("
                f"Min: {lowest_nic_count}, Max: {highest_nic_count}). Compute Resource will be created with "
                f"{lowest_nic_count} network cards.",
                FailureLevel.WARNING,
            )

        if placement_group_enabled and len(instance_types_info.keys()) > 1:
            self._add_failure(
                f"Enabling placement groups for queue: {queue_name} may result in Insufficient Capacity Errors due to "
                f"the use of multiple instance types for Compute Resource: {compute_resource_name} ("
                f"https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/placement-groups.html#placement-groups-cluster).",
                FailureLevel.WARNING,
            )


class InstancesAllocationStrategyValidator(Validator, _FlexibleInstanceTypesValidatorMixin):
    """Confirm Allocation Strategy matches with the Capacity Type."""

    def _validate(self, compute_resource_name: str, capacity_type: Enum, allocation_strategy: Enum, **kwargs):
        """On-demand Capacity type only supports "lowest-price" allocation strategy."""
        if (
            capacity_type == cluster_config.CapacityType.ONDEMAND
            and allocation_strategy != cluster_config.AllocationStrategy.LOWEST_PRICE
        ):
            self._add_failure(
                f"Compute Resource {compute_resource_name} is using an OnDemand CapacityType but the Allocation "
                f"Strategy specified is {allocation_strategy.value}. OnDemand CapacityType can only use '"
                f"{cluster_config.AllocationStrategy.LOWEST_PRICE.value}' allocation strategy.",
                FailureLevel.ERROR,
            )


class InstancesMemorySchedulingValidator(Validator, _FlexibleInstanceTypesValidatorMixin):
    """Validate support for Memory-based Scheduling when using Flexible Instance Types."""

    def _validate(
        self,
        compute_resource_name: str,
        instance_types_info: Dict[str, InstanceTypeInfo],
        memory_scheduling_enabled: bool,
        **kwargs,
    ):
        """Memory-based scheduling is NOT supported for Compute Resources with multiple instance types."""
        if memory_scheduling_enabled and len(instance_types_info.items()) > 1:
            self._add_failure(
                "Memory-based scheduling is only supported for Compute Resources using either 'InstanceType' or "
                f"'Instances' with one instance type. Compute Resource {compute_resource_name} has more than "
                "one instance type specified.",
                FailureLevel.ERROR,
            )
