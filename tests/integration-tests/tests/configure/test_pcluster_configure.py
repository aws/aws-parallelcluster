# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import logging
from datetime import datetime
from os import environ

import boto3
import pexpect
import pytest
import yaml
from assertpy import assert_that
from cfn_stacks_factory import CfnVpcStack
from conftest import inject_additional_config_settings
from conftest_networking import CIDR_FOR_CUSTOM_SUBNETS
from utils import get_instance_info

PROMPTS = {
    "region": lambda region: {"prompt": r"AWS Region ID \[.*\]: ", "response": region},
    "key_pair": lambda key_name: {"prompt": r"EC2 Key Pair Name \[.*\]: ", "response": key_name},
    "scheduler": lambda scheduler: {"prompt": r"Scheduler \[slurm\]: ", "response": scheduler},
    "os": lambda os: {"prompt": r"Operating System \[alinux2\]: ", "response": os, "skip_for_batch": True},
    "head_instance_type": lambda instance: {"prompt": r"Head node instance type \[t.\.micro\]: ", "response": instance},
    "no_of_queues": lambda n: {"prompt": rf"Number of queues \[{n}\]: ", "response": f"{n}", "skip_for_batch": True},
    "queue_name": lambda queue, name: {"prompt": rf"Name of queue {queue} \[queue{queue}\]: ", "response": name},
    "no_of_compute_resources": lambda queue_name, queue, n: {
        "prompt": rf"Number of compute resources for {queue_name} \[{queue}\]: ",
        "response": f"{n}",
        "skip_for_batch": True,
    },
    "compute_instance_type": lambda resource, queue_name, instance: {
        "prompt": rf"Compute instance type for compute resource {resource} in {queue_name} \[t.\.micro\]: ",
        "response": instance,
        "skip_for_batch": True,
    },
    "enable_efa": lambda response: {
        "prompt": r"Enable EFA .* \(y/n\) \[y\]:",
        "response": response,
    },
    "placement_group": lambda response: {"prompt": r"Placement Group name \[\]:", "response": response},
    "vpc_creation": lambda response: {"prompt": r"Automate VPC creation\? \(y/n\) \[n\]: ", "response": response},
    "vpc_id": lambda vpc_id: {"prompt": r"VPC ID \[vpc-.+\]: ", "response": vpc_id},
    "subnet_creation": lambda response: {"prompt": r"Automate Subnet creation\? \(y/n\) \[y\]: ", "response": response},
}


def test_pcluster_configure(
    request, vpc_stack, key_name, region, os, instance, scheduler, clusters_factory, test_datadir, architecture
):
    """Verify that the config file produced by `pcluster configure` can be used to create a cluster."""
    skip_if_unsupported_test_options_were_used(request)
    config_path = test_datadir / "config.yaml"

    _create_and_test_standard_configuration(request, config_path, region, key_name, scheduler, os, instance, vpc_stack)

    inject_additional_config_settings(config_path, request, region, architecture)
    clusters_factory(config_path)


def test_pcluster_configure_avoid_bad_subnets(
    request,
    vpc_stack,
    subnet_in_use1_az3,
    pcluster_config_reader,
    key_name,
    region,
    os,
    instance,
    scheduler,
    clusters_factory,
    test_datadir,
):
    """
    When config file contains a subnet that does not have the desired instance type, verify that `pcluster configure`
    can correct the head_node/compute_subnet_id fields using qualified subnets and show a message for the omitted
    subnets
    """
    config_path = test_datadir / "config.yaml"
    bad_subnets_prompts = (
        standard_first_stage_prompts(region, key_name, scheduler, os, instance)
        + standard_queue_prompts(scheduler, instance, region)
        + [
            PROMPTS["vpc_creation"]("n"),
            PROMPTS["vpc_id"](vpc_stack.cfn_outputs["VpcId"]),
            PROMPTS["subnet_creation"]("n"),
            prompt_head_node_subnet_id(subnet_id="", no_of_omitted_subnets=3),
            prompt_compute_node_subnet_id(subnet_id="", head_node_subnet_id="", no_of_omitted_subnets=3),
        ]
    )
    stages = orchestrate_pcluster_configure_stages(prompts=bad_subnets_prompts, scheduler=scheduler)
    assert_configure_workflow(request, region, stages, config_path)
    assert_config_contains_expected_values(key_name, scheduler, os, instance, region, None, None, config_path)


def test_region_without_t2micro(
    request, vpc_stack: CfnVpcStack, pcluster_config_reader, key_name, region, os, scheduler, test_datadir
):
    """
    Verify the default instance type (free tier) is retrieved dynamically according to region.
    In other words, t3.micro is retrieved when the region does not contain t2.micro
    """
    config_path = test_datadir / "config.yaml"
    region_without_t2micro_prompts = (
        standard_first_stage_prompts(region, key_name, scheduler, os, "")
        + standard_queue_prompts(scheduler, "", region)
        + standard_vpc_subnet_prompts(vpc_stack)
    )
    stages = orchestrate_pcluster_configure_stages(region_without_t2micro_prompts, scheduler)
    assert_configure_workflow(request, region, stages, config_path)
    assert_config_contains_expected_values(
        key_name,
        scheduler,
        os,
        "",
        region,
        vpc_stack.get_public_subnet(),
        vpc_stack.get_private_subnet(),
        config_path,
    )


@pytest.mark.parametrize(
    "efa_response, efa_config, placement_group_response_type",
    [
        ("y", {"enabled": True}, "default"),
        ("y", {"enabled": True}, "custom"),
        ("n", {"enabled": False}, "none"),
    ],
)
def test_efa_and_placement_group(
    request,
    vpc_stack: CfnVpcStack,
    key_name,
    region,
    os,
    instance,
    architecture,
    scheduler,
    clusters_factory,
    test_datadir,
    efa_response,
    efa_config,
    placement_group_response_type,
    placement_group_stack,
):
    config_path = test_datadir / "config.yaml"

    placement_group_config = expected_placement_group_configuration(
        placement_group_response_type, placement_group_stack.cfn_resources["PlacementGroup"]
    )

    queue_prompts = [
        PROMPTS["no_of_queues"](1),
        PROMPTS["queue_name"](queue=1, name="myqueue"),
        PROMPTS["no_of_compute_resources"](queue_name="myqueue", queue=1, n=1),
        PROMPTS["compute_instance_type"](resource=1, queue_name="myqueue", instance=instance),
        PROMPTS["enable_efa"](efa_response),
        prompt_max_size(scheduler=scheduler),
    ]

    if efa_response == "y":
        queue_prompts.append(PROMPTS["placement_group"](placement_group_config["response"]))

    standard_prompts = (
        standard_first_stage_prompts(region, key_name, scheduler, os, instance)
        + queue_prompts
        + standard_vpc_subnet_prompts(vpc_stack)
    )
    stages = orchestrate_pcluster_configure_stages(standard_prompts, scheduler)
    assert_configure_workflow(request, region, stages, config_path)
    assert_config_contains_expected_values(
        key_name,
        scheduler,
        os,
        instance,
        region,
        vpc_stack.get_public_subnet(),
        vpc_stack.get_private_subnet(),
        config_path,
        efa_config=efa_config,
        placement_group_config=placement_group_config["configuration"],
    )
    inject_additional_config_settings(config_path, request, region, architecture)
    clusters_factory(config_path)


def test_efa_unsupported(request, vpc_stack, key_name, region, os, instance, scheduler, clusters_factory, test_datadir):
    config_path = test_datadir / "config.yaml"
    _create_and_test_standard_configuration(request, config_path, region, key_name, scheduler, os, instance, vpc_stack)


def _create_and_test_standard_configuration(
    request, config_path, region, key_name, scheduler, os, instance, vpc_stack: CfnVpcStack
):
    standard_prompts = (
        standard_first_stage_prompts(region, key_name, scheduler, os, instance)
        + standard_queue_prompts(scheduler, instance, region)
        + standard_vpc_subnet_prompts(vpc_stack)
    )
    stages = orchestrate_pcluster_configure_stages(standard_prompts, scheduler)
    assert_configure_workflow(request, region, stages, config_path)
    assert_config_contains_expected_values(
        key_name,
        scheduler,
        os,
        instance,
        region,
        vpc_stack.get_public_subnet(),
        vpc_stack.get_private_subnet(),
        config_path,
    )


def expected_placement_group_configuration(response_type, existing_placement_group):
    responses = {
        "default": {"response": "", "configuration": {"enabled": True}},
        "custom": {
            "response": existing_placement_group,
            "configuration": {"enabled": True, "id": existing_placement_group},
        },
        "none": {"response": None, "configuration": None},
    }
    return responses[response_type]


def standard_first_stage_prompts(region, key_name, scheduler, os, instance):
    return [
        PROMPTS["region"](region),
        PROMPTS["key_pair"](key_name),
        PROMPTS["scheduler"](scheduler),
        PROMPTS["os"](os),
        PROMPTS["head_instance_type"](instance),
    ]


def standard_queue_prompts(scheduler, instance, region, size=""):
    queue_prompts = [
        PROMPTS["no_of_queues"](1),
        PROMPTS["queue_name"](queue=1, name="myqueue"),
        PROMPTS["no_of_compute_resources"](queue_name="myqueue", queue=1, n=1),
        PROMPTS["compute_instance_type"](resource=1, queue_name="myqueue", instance=instance),
    ]

    is_efa_supported = False
    if instance:
        is_efa_supported = get_instance_info(instance, region).get("NetworkInfo", {}).get("EfaSupported", False)
    if is_efa_supported:
        queue_prompts.append(PROMPTS["enable_efa"]("y"))

    queue_prompts.append(prompt_max_size(scheduler=scheduler, size=size))

    if is_efa_supported:
        queue_prompts.append(PROMPTS["placement_group"](""))

    return queue_prompts


def standard_vpc_subnet_prompts(vpc_stack: CfnVpcStack):
    return [
        PROMPTS["vpc_creation"]("n"),
        PROMPTS["vpc_id"](vpc_stack.cfn_outputs["VpcId"]),
        PROMPTS["subnet_creation"]("n"),
        prompt_head_node_subnet_id(subnet_id=vpc_stack.get_public_subnet()),
        prompt_compute_node_subnet_id(
            subnet_id=vpc_stack.get_private_subnet(),
            head_node_subnet_id=vpc_stack.get_public_subnet(),
        ),
    ]


def prompt_head_node_subnet_id(subnet_id, no_of_omitted_subnets=0):
    # When there are omitted subnets, a note should be printed
    omitted_note = "Note: {0} subnet.+not listed.+".format(no_of_omitted_subnets) if no_of_omitted_subnets else ""
    return {"prompt": rf"{omitted_note}head node subnet ID \[subnet-.+\]: ", "response": subnet_id}


def prompt_compute_node_subnet_id(subnet_id, head_node_subnet_id, no_of_omitted_subnets=0):
    omitted_note = "Note: {0} subnet.+not listed.+".format(no_of_omitted_subnets) if no_of_omitted_subnets else ""

    # Default compute subnet follows the selection of head node subnet
    default_compute_subnet = head_node_subnet_id or "subnet-.+"
    return {"prompt": rf"{omitted_note}compute subnet ID \[{default_compute_subnet}\]: ", "response": subnet_id}


def prompt_max_size(scheduler, size=""):
    size_name = "vCPU" if scheduler == "awsbatch" else "instance count"
    return {"prompt": rf"Maximum {size_name} \[10\]: ", "response": f"{size}"}


def skip_if_unsupported_test_options_were_used(request):
    unsupported_options = get_unsupported_test_runner_options(request)
    if unsupported_options:
        skip_message = f"These test_runner CLI options are not supported by this test: {', '.join(unsupported_options)}"
        logging.info(skip_message)
        pytest.skip(skip_message)


def get_unsupported_test_runner_options(request):
    """Return list of CLI args exposed by test_runner.py that this test doesn't support which were also used."""
    unsupported_options = ["cluster"]
    return [option for option in unsupported_options if request.config.getoption(option) is not None]


def assert_configure_workflow(request, region, stages, config_path):
    logging.info(f"Using `pcluster configure` to write a configuration to {config_path}")
    environ["AWS_DEFAULT_REGION"] = region
    configure_process = pexpect.spawn(f"pcluster configure --config {config_path}", encoding="utf-8", timeout=90)
    output_dir = request.config.getoption("output_dir")
    with open(
        f"{output_dir}/spawned-process-log-{datetime.now().strftime('%d-%m-%Y-%H:%M:%S.%f')}", "w", encoding="utf-8"
    ) as spawned_process_log:
        configure_process.logfile = spawned_process_log
        for stage in stages:
            configure_prompt_status = configure_process.expect(stage.get("prompt"))
            assert_that(configure_prompt_status).is_equal_to(0)
            configure_process.sendline(stage.get("response"))

        # Expecting EOF verifies that `pcluster configure` finished as expected.
        configure_process.expect(pexpect.EOF)
        configure_process.close()
        assert_that(configure_process.exitstatus).is_equal_to(0)

    # Log the generated config's contents so debugging doesn't always require digging through Jenkins artifacts
    with open(config_path, encoding="utf-8") as config_file:
        logging.info(f"Configuration file generated by `pcluster configure`\n{config_file.read()}")


def assert_config_contains_expected_values(
    key_name,
    scheduler,
    os,
    instance,
    region,
    head_node_subnet_id,
    compute_subnet_id,
    config_path,
    efa_config=None,
    placement_group_config=None,
):
    """
    :param efa_config: Dictionary describing EFA configuration
        {
            "enabled": True
        }
    :param placement_group_config: Dictionary describing the placement_group configuration
        {
            "enabled": True,
            "id": <PlacementGroupName>
        }
    """
    with open(config_path, encoding="utf-8") as conf_file:
        config = yaml.safe_load(conf_file)

    # Assert that the config object contains the expected values
    param_validators = [
        {"parameter_path": ["Region"], "expected_value": region},
        {"parameter_path": ["HeadNode", "Ssh", "KeyName"], "expected_value": key_name},
        {"parameter_path": ["Scheduling", "Scheduler"], "expected_value": scheduler},
        {"parameter_path": ["Image", "Os"], "expected_value": os if scheduler != "awsbatch" else "alinux2"},
        {"parameter_path": ["HeadNode", "InstanceType"], "expected_value": instance},
        {"parameter_path": ["HeadNode", "Networking", "SubnetId"], "expected_value": head_node_subnet_id},
        {
            "parameter_path": [
                "Scheduling",
                "AwsBatchQueues" if scheduler == "awsbatch" else "SlurmQueues",
                0,
                "Networking",
                "SubnetIds",
                0,
            ],
            "expected_value": compute_subnet_id,
        },
    ]

    if scheduler == "slurm":
        param_validators += [
            {
                "parameter_path": [
                    "Scheduling",
                    "SlurmQueues",
                    0,
                    "ComputeResources",
                    0,
                    "Instances",
                    0,
                    "InstanceType",
                ],
                "expected_value": instance,
            },
            {
                "parameter_path": ["Scheduling", "SlurmQueues", 0, "ComputeResources", 0, "MinCount"],
                "expected_value": 0,
            },
        ]
        if efa_config and "enabled" in efa_config:
            param_validators.append(
                {
                    "parameter_path": ["Scheduling", "SlurmQueues", 0, "ComputeResources", 0, "Efa", "Enabled"],
                    "expected_value": efa_config["enabled"],
                }
            )
        if placement_group_config:
            if "enabled" in placement_group_config:
                param_validators.append(
                    {
                        "parameter_path": ["Scheduling", "SlurmQueues", 0, "Networking", "PlacementGroup", "Enabled"],
                        "expected_value": placement_group_config["enabled"],
                    }
                )
            if "id" in placement_group_config:
                param_validators.append(
                    {
                        "parameter_path": ["Scheduling", "SlurmQueues", 0, "Networking", "PlacementGroup", "Id"],
                        "expected_value": placement_group_config["id"],
                    }
                )
    elif scheduler == "awsbatch":
        param_validators += [
            {
                "parameter_path": ["Scheduling", "AwsBatchQueues", 0, "ComputeResources", 0, "MinvCpus"],
                "expected_value": 0,
            }
        ]
    for validator in param_validators:
        expected_value = validator.get("expected_value")
        logging.info(validator.get("parameter_path"))
        if expected_value in ("", None):
            # if expected_value is empty, skip the assertion.
            continue
        observed_value = _get_value_by_nested_key(config, validator.get("parameter_path"))
        assert_that(observed_value).is_equal_to(expected_value)


def _get_value_by_nested_key(d, keys):
    """Get the value specified by *keys (nested) in d (dict)."""
    _d = d
    for key in keys:
        _d = _d[key]
    return _d


def orchestrate_pcluster_configure_stages(prompts, scheduler):
    # When a user selects Batch as the scheduler, pcluster configure does not prompt for OS or compute instance type.
    return [prompt for prompt in prompts if scheduler != "awsbatch" or not prompt.get("skip_for_batch")]


@pytest.fixture(scope="class")
def subnet_in_use1_az3(vpc_stack):
    # Subnet used to test the functionality of avoiding subnet in AZs that do not have user specified instance types
    # Hard coding implementation to run on us-east-1 and create subnet in use1_az3 without c5.xlarge
    # Use use1_az3 as AZ, which does not have c5.xlarge
    # To-do: extend code to support arbitrary region and arbitrary instance types

    # Verify that use1_az3 does not have c5.xlarge.
    ec2_client = boto3.client("ec2", region_name="us-east-1")
    paginator = ec2_client.get_paginator("describe_instance_type_offerings")
    page_iterator = paginator.paginate(
        LocationType="availability-zone-id",
        Filters=[{"Name": "instance-type", "Values": ["c5.xlarge"]}, {"Name": "location", "Values": ["use1-az3"]}],
    )
    offerings = []
    for page in page_iterator:
        offerings.extend(page["InstanceTypeOfferings"])
    logging.info(
        "Asserting that c5.xlarge is not in use1-az3. If assertion fails, "
        "c5.xlarge has been added to use1-az3, change the test code so that we are testing the case where"
        " a specific instance type is not available in a chosen subnet"
    )
    assert_that(offerings).is_empty()
    subnet_id = ec2_client.create_subnet(
        AvailabilityZoneId="use1-az3", CidrBlock=CIDR_FOR_CUSTOM_SUBNETS[-1], VpcId=vpc_stack.cfn_outputs["VpcId"]
    )["Subnet"]["SubnetId"]
    yield subnet_id
    ec2_client.delete_subnet(SubnetId=subnet_id)
