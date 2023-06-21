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
import logging

import pytest
from marshmallow import ValidationError

from pcluster.schemas.cluster_schema import InstanceRequirementsSchema, SlurmComputeResourceSchema


@pytest.mark.parametrize(
    "compute_resource_config, failure_message",
    [
        pytest.param(
            {"Name": "cr-single", "InstanceType": "c5.2xlarge"}, None, id="Using single instance type only is correct"
        ),
        pytest.param(
            {"Name": "cr-multi", "Instances": [{"InstanceType": "c5.2xlarge"}, {"InstanceType": "c5.4xlarge"}]},
            None,
            id="Using multiple instance type only is correct",
        ),
        pytest.param(
            {
                "Name": "cr-multi",
                "InstanceRequirements": {"MinvCpus": 1, "MaxvCpus": 5, "MinMemoryMib": 1, "MaxMemoryMib": 5},
            },
            None,
            id="Using InstanceRequirements only is correct",
        ),
        pytest.param(
            {
                "Name": "cr-single-multi",
                "InstanceType": "c5.2xlarge",
                "Instances": [{"InstanceType": "c5.2xlarge"}, {"InstanceType": "c5.4xlarge"}],
            },
            "A Compute Resource needs to specify either InstanceType, Instances or InstanceRequirements.",
            id="Using single single and multiple instance types together should fail",
        ),
        pytest.param(
            {
                "Name": "cr-single-requirements",
                "InstanceType": "c5.2xlarge",
                "InstanceRequirements": {"MinvCpus": 1, "MaxvCpus": 5, "MinMemoryMib": 1, "MaxMemoryMib": 5},
            },
            "A Compute Resource needs to specify either InstanceType, Instances or InstanceRequirements.",
            id="Using single instance type and InstanceRequirements together should fail",
        ),
        pytest.param(
            {
                "Name": "cr-single-requirements",
                "Instances": [{"InstanceType": "c5.2xlarge"}, {"InstanceType": "c5.4xlarge"}],
                "InstanceRequirements": {"MinvCpus": 1, "MaxvCpus": 5, "MinMemoryMib": 1, "MaxMemoryMib": 5},
            },
            "A Compute Resource needs to specify either InstanceType, Instances or InstanceRequirements.",
            id="Using multiple instance types and InstanceRequirements together should fail",
        ),
    ],
)
def test_compute_resource_definitions_are_mutually_exclusive(compute_resource_config, failure_message):
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SlurmComputeResourceSchema().load(compute_resource_config)
    else:
        ir_schema = SlurmComputeResourceSchema()
        ir_obj = ir_schema.load(compute_resource_config)
        ir_json = ir_schema.dump(ir_obj)

        logging.debug("Rendered resource: ", ir_json)


@pytest.mark.parametrize(
    "instance_requirement_config, failure_message",
    [
        pytest.param(
            {"MinvCpus": 1, "MaxvCpus": 5, "MinMemoryMib": 1, "MaxMemoryMib": 5},
            None,
            id="Using none of them is correct",
        ),
        pytest.param(
            {
                "MinvCpus": 1,
                "MaxvCpus": 5,
                "MinMemoryMib": 1,
                "MaxMemoryMib": 5,
                "AllowedInstanceTypes": ["in1", "in2"],
            },
            None,
            id="Using only AllowedInstanceTypes is correct",
        ),
        pytest.param(
            {
                "MinvCpus": 1,
                "MaxvCpus": 5,
                "MinMemoryMib": 1,
                "MaxMemoryMib": 5,
                "ExcludedInstanceTypes": ["in1", "in2"],
            },
            None,
            id="Using only ExcludedInstanceTypes is correct",
        ),
        pytest.param(
            {
                "MinvCpus": 1,
                "MaxvCpus": 5,
                "MinMemoryMib": 1,
                "MaxMemoryMib": 5,
                "AllowedInstanceTypes": ["in1", "in2"],
                "ExcludedInstanceTypes": ["in1", "in2"],
            },
            "Either AllowedInstanceTypes or ExcludedInstanceTypes can be used " "in InstanceRequirements definition.",
            id="Using both AllowedInstanceTypes and ExcludedInstanceTypes should fail",
        ),
    ],
)
def test_allowed_and_excluded_instance_types_list_are_mutually_exclusive(instance_requirement_config, failure_message):
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            InstanceRequirementsSchema().load(instance_requirement_config)
    else:
        ir_schema = InstanceRequirementsSchema()
        ir_obj = ir_schema.load(instance_requirement_config)
        ir_json = ir_schema.dump(ir_obj)
        logging.debug("Rendered resource: ", ir_json)


@pytest.mark.parametrize(
    "instance_requirement_config, should_be_set",
    [
        pytest.param(
            {
                "MinvCpus": 1,
                "MinMemoryMib": 1,
            },
            False,
            id="When AcceleratorCount is not set Manufacturer and Type should not be set",
        ),
        pytest.param(
            {"MinvCpus": 1, "MinMemoryMib": 1, "AcceleratorCount": 0},
            False,
            id="When AcceleratorCount is 0 Manufacturer and Type should not be set",
        ),
        pytest.param(
            {"MinvCpus": 1, "MinMemoryMib": 1, "AcceleratorCount": 1},
            True,
            id="When AcceleratorCount is > 0 Manufacturer and Type should be set",
        ),
    ],
)
def test_when_setting_accelerator_count_also_manufacturer_and_type_should_be_set(
    instance_requirement_config, should_be_set
):
    ir_schema = InstanceRequirementsSchema()
    ir_obj = ir_schema.load(instance_requirement_config)
    ir_json = ir_schema.dump(ir_obj)
    logging.debug("Rendered resource: ", ir_json)

    if should_be_set:
        assert ["gpu"] == ir_obj.accelerator_types
        assert ["nvidia"] == ir_obj.accelerator_manufacturers
    else:
        assert ir_obj.accelerator_types is None
        assert ir_obj.accelerator_manufacturers is None


def test_default_behavior_is_enforced():
    config = {"MinvCpus": 1, "MinMemoryMib": 1, "AcceleratorCount": 1}
    ir_schema = InstanceRequirementsSchema()
    ir_obj = ir_schema.load(config)
    ir_json = ir_schema.dump(ir_obj)
    logging.debug("Rendered resource: ", ir_json)

    assert ["included"] == ir_obj.bare_metal
    assert ["current"] == ir_obj.instance_generations
