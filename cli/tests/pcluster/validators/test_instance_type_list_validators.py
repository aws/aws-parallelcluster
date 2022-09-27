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
from typing import Dict, List

import pytest
from assertpy import assert_that

from pcluster.aws.aws_resources import InstanceTypeInfo
from pcluster.config.cluster_config import AllocationStrategy, CapacityType
from pcluster.validators.instance_type_list_validators import (
    InstanceTypeListAcceleratorsValidator,
    InstanceTypeListAllocationStrategyValidator,
    InstanceTypeListCPUValidator,
    InstanceTypeListEFAValidator,
    InstanceTypeListMemorySchedulingValidator,
    InstanceTypeListNetworkingValidator,
)
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "compute_resource_name, instance_types_info, disable_simultaneous_multithreading, expected_message",
    [
        # Instance Types should have the same number of CPUs
        (
            "TestComputeResource",
            {
                "t2.micro": InstanceTypeInfo(
                    {"InstanceType": "t2.micro", "VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2}}
                ),
                "t3.micro": InstanceTypeInfo(
                    {"InstanceType": "t3.micro", "VCpuInfo": {"DefaultVCpus": 5, "DefaultCores": 2}}
                ),
            },
            False,
            "Instance types listed under Compute Resource TestComputeResource must have the same number of vCPUs "
            "({'t2.micro': 4, 't3.micro': 5}).",
        ),
        (
            "TestComputeResource",
            {
                "t2.micro": InstanceTypeInfo(
                    {"InstanceType": "t2.micro", "VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2}}
                ),
                "t3.micro": InstanceTypeInfo(
                    {"InstanceType": "t3.micro", "VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2}}
                ),
            },
            False,
            "",
        ),
        # InstanceTypes should have the same number of cores if simultaneous multithreading is disabled
        (
            "TestComputeResource",
            {
                "t2.micro": InstanceTypeInfo(
                    {"InstanceType": "t2.micro", "VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 1}}
                ),
                "t3.micro": InstanceTypeInfo(
                    {"InstanceType": "t3.micro", "VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2}}
                ),
            },
            True,
            "Instance types listed under Compute Resource TestComputeResource must have the same number of CPU "
            "cores when Simultaneous Multithreading is disabled ({'t2.micro': 1, 't3.micro': 2}).",
        ),
        (
            "TestComputeResource",
            {
                "t2.micro": InstanceTypeInfo({"VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 1}}),
                "t3.micro": InstanceTypeInfo({"VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2}}),
            },
            False,
            "",
        ),
    ],
)
def test_instance_type_list_cpu_validator(
    compute_resource_name,
    instance_types_info,
    disable_simultaneous_multithreading,
    expected_message,
):
    actual_failures = InstanceTypeListCPUValidator().execute(
        compute_resource_name,
        instance_types_info,
        disable_simultaneous_multithreading,
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "compute_resource_name, instance_types_info, expected_message, logger_message",
    [
        # Instance Types should have the same number of GPUs
        (
            "TestComputeResource",
            {
                "g4dn.xlarge": InstanceTypeInfo(
                    {
                        "InstanceType": "g4dn.xlarge",
                        "GpuInfo": {
                            "Gpus": [
                                {"Name": "T4", "Manufacturer": "NVIDIA", "Count": 1, "MemoryInfo": {"SizeInMiB": 16384}}
                            ],
                            "TotalGpuMemoryInMiB": 16384,
                        },
                    }
                ),
                "g5.xlarge": InstanceTypeInfo(
                    {
                        "InstanceType": "g5.xlarge",
                        "GpuInfo": {
                            "Gpus": [
                                {
                                    "Name": "A10G",
                                    "Manufacturer": "NVIDIA",
                                    "Count": 2,
                                    "MemoryInfo": {"SizeInMiB": 24576},
                                }
                            ],
                            "TotalGpuMemoryInMiB": 24576,
                        },
                    }
                ),
            },
            "Instance types listed under Compute Resource TestComputeResource must have the same number of GPUs ({"
            "'g4dn.xlarge': 1, 'g5.xlarge': 2}).",
            "",
        ),
        (
            "TestComputeResource",
            {
                "g4dn.xlarge": InstanceTypeInfo(
                    {
                        "GpuInfo": {
                            "Gpus": [
                                {"Name": "T4", "Manufacturer": "NVIDIA", "Count": 2, "MemoryInfo": {"SizeInMiB": 16384}}
                            ],
                            "TotalGpuMemoryInMiB": 16384,
                        },
                    }
                ),
                "g5.xlarge": InstanceTypeInfo(
                    {
                        "GpuInfo": {
                            "Gpus": [
                                {
                                    "Name": "A10G",
                                    "Manufacturer": "NVIDIA",
                                    "Count": 2,
                                    "MemoryInfo": {"SizeInMiB": 24576},
                                }
                            ],
                            "TotalGpuMemoryInMiB": 24576,
                        },
                    }
                ),
            },
            "",
            "",
        ),
        # Instance Types should have the same number of Accelerators
        (
            "TestComputeResource",
            {
                "inf1.6xlarge": InstanceTypeInfo(
                    {
                        "InstanceType": "inf1.6xlarge",
                        "InferenceAcceleratorInfo": {
                            "Accelerators": [{"Count": 4, "Name": "Inferentia", "Manufacturer": "AWS"}]
                        },
                    }
                ),
                "inf1.2xlarge": InstanceTypeInfo(
                    {
                        "InstanceType": "inf1.2xlarge",
                        "InferenceAcceleratorInfo": {
                            "Accelerators": [{"Count": 1, "Name": "Inferentia", "Manufacturer": "AWS"}]
                        },
                    }
                ),
            },
            "Instance types listed under Compute Resource TestComputeResource must have the same number of Inference "
            "Accelerators ({'inf1.6xlarge': 4, 'inf1.2xlarge': 1}).",
            "",
        ),
        (
            "TestComputeResource",
            {
                "inf1.6xlarge": InstanceTypeInfo(
                    {
                        "InferenceAcceleratorInfo": {
                            "Accelerators": [{"Count": 4, "Name": "Inferentia", "Manufacturer": "AWS"}]
                        },
                    }
                ),
                "inf1.2xlarge": InstanceTypeInfo(
                    {
                        "InferenceAcceleratorInfo": {
                            "Accelerators": [{"Count": 4, "Name": "Inferentia", "Manufacturer": "AWS"}]
                        },
                    }
                ),
            },
            "",
            "",
        ),
        # Instance Types should have the same GPU manufacturer
        (
            "TestComputeResource",
            {
                "g4dn.xlarge": InstanceTypeInfo(
                    {
                        "InstanceType": "g4dn.xlarge",
                        "GpuInfo": {
                            "Gpus": [
                                {"Name": "T4", "Manufacturer": "NVIDIA", "Count": 2, "MemoryInfo": {"SizeInMiB": 16384}}
                            ],
                            "TotalGpuMemoryInMiB": 16384,
                        },
                    }
                ),
                "g5.xlarge": InstanceTypeInfo(
                    {
                        "InstanceType": "g5.xlarge",
                        "GpuInfo": {
                            "Gpus": [
                                {
                                    "Name": "A10G",
                                    "Manufacturer": "OtherGPUManufacturers",
                                    "Count": 2,
                                    "MemoryInfo": {"SizeInMiB": 24576},
                                }
                            ],
                            "TotalGpuMemoryInMiB": 24576,
                        },
                    }
                ),
            },
            "Instance types listed under Compute Resource TestComputeResource must have the same GPU manufacturer ({"
            "'g4dn.xlarge': 'NVIDIA', 'g5.xlarge': 'OtherGPUManufacturers'}).",
            "offers native support for NVIDIA manufactured GPUs only.* GPU Info: .*Please "
            "make sure to use a custom AMI",
        ),
        (
            "TestComputeResource",
            {
                "g4dn.xlarge": InstanceTypeInfo(
                    {
                        "GpuInfo": {
                            "Gpus": [
                                {"Name": "T4", "Manufacturer": "NVIDIA", "Count": 2, "MemoryInfo": {"SizeInMiB": 16384}}
                            ],
                            "TotalGpuMemoryInMiB": 16384,
                        },
                    }
                ),
                "g5.xlarge": InstanceTypeInfo(
                    {
                        "GpuInfo": {
                            "Gpus": [
                                {
                                    "Name": "A10G",
                                    "Manufacturer": "NVIDIA",
                                    "Count": 2,
                                    "MemoryInfo": {"SizeInMiB": 24576},
                                }
                            ],
                            "TotalGpuMemoryInMiB": 24576,
                        },
                    }
                ),
            },
            "",
            "",
        ),
        # Instance Types should have the same Accelerator Manufacturer (Inferentia)
        (
            "TestComputeResource",
            {
                "inf1.6xlarge": InstanceTypeInfo(
                    {
                        "InstanceType": "inf1.6xlarge",
                        "InferenceAcceleratorInfo": {
                            "Accelerators": [{"Count": 4, "Name": "Inferentia", "Manufacturer": "AWS"}]
                        },
                    }
                ),
                "inf1.2xlarge": InstanceTypeInfo(
                    {
                        "InstanceType": "inf1.2xlarge",
                        "InferenceAcceleratorInfo": {
                            "Accelerators": [{"Count": 4, "Name": "Inferentia", "Manufacturer": "NotAWS"}]
                        },
                    }
                ),
            },
            "Instance types listed under Compute Resource TestComputeResource must have the same inference "
            "accelerator manufacturer ({'inf1.6xlarge': 'AWS', 'inf1.2xlarge': 'NotAWS'}).",
            "offers native support for 'AWS' manufactured Inference Accelerators only.* accelerator info: .*Please "
            "make sure to use a custom AMI",
        ),
        (
            "TestComputeResource",
            {
                "inf1.6xlarge": InstanceTypeInfo(
                    {
                        "InferenceAcceleratorInfo": {
                            "Accelerators": [{"Count": 4, "Name": "Inferentia", "Manufacturer": "AWS"}]
                        },
                    }
                ),
                "inf1.2xlarge": InstanceTypeInfo(
                    {
                        "InferenceAcceleratorInfo": {
                            "Accelerators": [{"Count": 4, "Name": "Inferentia", "Manufacturer": "AWS"}]
                        },
                    }
                ),
            },
            "",
            "",
        ),
    ],
)
def test_instance_type_list_accelerators_validator(
    compute_resource_name, instance_types_info, expected_message, logger_message, caplog
):
    actual_failures = InstanceTypeListAcceleratorsValidator().execute(
        compute_resource_name,
        instance_types_info,
    )
    assert_failure_messages(actual_failures, expected_message)
    if logger_message:
        assert_that(caplog.text).matches(logger_message)


@pytest.mark.parametrize(
    "compute_resource_name, instance_types_info, efa_enabled, expected_message",
    [
        # Instance Types should have the same EFA support status if EFA is enabled
        (
            "TestComputeResource",
            {
                "t2.micro": InstanceTypeInfo({"NetworkInfo": {"EfaSupported": False}}),
                "t3.micro": InstanceTypeInfo({"NetworkInfo": {"EfaSupported": False}}),
                "c5n.18xlarge": InstanceTypeInfo({"NetworkInfo": {"EfaSupported": True}}),
            },
            True,
            "Instance type(s) (t2.micro,t3.micro) do not support EFA and cannot be launched when EFA is enabled in "
            "Compute Resource: TestComputeResource.",
        ),
        (
            "TestComputeResource",
            {
                "c5n.9xlarge": InstanceTypeInfo({"NetworkInfo": {"EfaSupported": True}}),
                "c5n.18xlarge": InstanceTypeInfo({"NetworkInfo": {"EfaSupported": True}}),
            },
            True,
            "",
        ),
        # If EFA is NOT enabled and one or more instance types supports EFA, a WARNING message should be printed
        (
            "TestComputeResource",
            {
                "t2.micro": InstanceTypeInfo({"NetworkInfo": {"EfaSupported": False}}),
                "t3.micro": InstanceTypeInfo({"NetworkInfo": {"EfaSupported": False}}),
                "c5n.18xlarge": InstanceTypeInfo({"NetworkInfo": {"EfaSupported": True}}),
            },
            False,
            "The EC2 instance type(s) selected (c5n.18xlarge) for the Compute Resource TestComputeResource support "
            "enhanced networking capabilities using Elastic Fabric Adapter (EFA). EFA enables you to run applications "
            "requiring high levels of inter-node communications at scale on AWS at no additional charge. You can "
            "update the cluster's configuration to enable EFA ("
            "https://docs.aws.amazon.com/parallelcluster/latest/ug/efa-v3.html).",
        ),
        # If EFA is enabled and NONE of the instance types supports EFA, an ERROR message should be printed
        (
            "TestComputeResource",
            {
                "t3.micro": InstanceTypeInfo({"NetworkInfo": {"EfaSupported": False}}),
                "t2.micro": InstanceTypeInfo({"NetworkInfo": {"EfaSupported": False}}),
            },
            True,
            "Instance type(s) (t2.micro,t3.micro) do not support EFA and cannot be launched when EFA is enabled in "
            "Compute Resource: TestComputeResource.",
        ),
    ],
)
def test_instance_type_list_efa_validator(
    compute_resource_name,
    instance_types_info,
    efa_enabled,
    expected_message,
):
    actual_failures = InstanceTypeListEFAValidator().execute(compute_resource_name, instance_types_info, efa_enabled)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "queue_name, compute_resource_name, instance_types_info, placement_group_enabled, expected_message",
    [
        # Instance Types with varying Maximum NICs will have the smallest one used when setting the launch template
        (
            "TestQueue10",
            "TestComputeResource",
            {
                "t2.micro": InstanceTypeInfo({"NetworkInfo": {"MaximumNetworkCards": 4}}),
                "t3.micro": InstanceTypeInfo({"NetworkInfo": {"MaximumNetworkCards": 2}}),
            },
            False,
            "Compute Resource TestComputeResource has instance types with varying numbers of network cards (Min: 2, "
            "Max: 4). Compute Resource will be created with 2 network cards.",
        ),
        (
            "TestQueue10",
            "TestComputeResource",
            {
                "t2.micro": InstanceTypeInfo({"NetworkInfo": {"MaximumNetworkCards": 4}}),
                "t3.micro": InstanceTypeInfo({"NetworkInfo": {"MaximumNetworkCards": 4}}),
            },
            False,
            "",
        ),
        # Using a placement group while having compute resources with multiple instance types increases the chances of
        # getting an Insufficient Capacity Error
        (
            "TestQueue11",
            "TestComputeResource",
            {},
            True,
            "Enabling placement groups for queue: TestQueue11 may result in Insufficient Capacity Errors due to the "
            "use of multiple instance types for Compute Resource: TestComputeResource ("
            "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/placement-groups.html#placement-groups-cluster).",
        ),
    ],
)
def test_instance_type_list_networking_validator(
    queue_name: str,
    compute_resource_name: str,
    instance_types_info: Dict[str, InstanceTypeInfo],
    placement_group_enabled: bool,
    expected_message: str,
):
    actual_failures = InstanceTypeListNetworkingValidator().execute(
        queue_name, compute_resource_name, instance_types_info, placement_group_enabled
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "compute_resource_name, capacity_type, allocation_strategy, expected_message",
    [
        # OnDemand Capacity type only supports "lowest-price" allocation strategy
        # Spot Capacity type supports both "lowest-price" and "capacity-optimized" allocation strategy
        (
            "TestComputeResource",
            CapacityType.ONDEMAND,
            AllocationStrategy.CAPACITY_OPTIMIZED,
            "Compute Resource TestComputeResource is using an OnDemand CapacityType but the Allocation Strategy "
            "specified is capacity-optimized. OnDemand CapacityType can only use 'lowest-price' allocation strategy.",
        ),
        ("TestComputeResource", CapacityType.ONDEMAND, AllocationStrategy.LOWEST_PRICE, ""),
    ],
)
def test_instance_type_list_allocation_strategy_validator(
    compute_resource_name: str, capacity_type: Enum, allocation_strategy: Enum, expected_message: str
):
    actual_failures = InstanceTypeListAllocationStrategyValidator().execute(
        compute_resource_name, capacity_type, allocation_strategy
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "compute_resource_name, instance_types_info, memory_scheduling_enabled, expected_message",
    [
        # Memory-based scheduling is supported for Compute Resource that use either 'InstanceType' or have a single
        # instance type under 'InstanceTypeList'
        (
            "TestComputeResource",
            {
                "t2.micro": InstanceTypeInfo({"VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2}}),
                "t3.micro": InstanceTypeInfo({"VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2}}),
            },
            True,
            "Memory-based scheduling is only supported for Compute Resources using either 'InstanceType' or "
            "'InstanceTypeList' with one instance type. Compute Resource TestComputeResource has more than one "
            "instance type specified.",
        ),
        (
            "TestComputeResource",
            {
                "t2.micro": InstanceTypeInfo({"VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2}}),
            },
            False,
            "",
        ),
    ],
)
def test_instance_type_list_memory_scheduling_validator(
    compute_resource_name: str,
    instance_types_info: List[InstanceTypeInfo],
    memory_scheduling_enabled: bool,
    expected_message: str,
):
    actual_failures = InstanceTypeListMemorySchedulingValidator().execute(
        compute_resource_name, instance_types_info, memory_scheduling_enabled
    )
    assert_failure_messages(actual_failures, expected_message)
