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
from os import environ

import boto3
import pexpect
import pytest
import yaml
from assertpy import assert_that
from conftest import inject_additional_config_settings


def test_pcluster_configure(
    request, vpc_stack, key_name, region, os, instance, scheduler, clusters_factory, test_datadir
):
    """Verify that the config file produced by `pcluster configure` can be used to create a cluster."""
    skip_if_unsupported_test_options_were_used(request)
    config_path = test_datadir / "config.yaml"
    stages = orchestrate_pcluster_configure_stages(
        region,
        key_name,
        scheduler,
        os,
        instance,
        vpc_stack.cfn_outputs["VpcId"],
        vpc_stack.cfn_outputs["PublicSubnetId"],
        vpc_stack.cfn_outputs["PrivateSubnetId"],
    )
    assert_configure_workflow(region, stages, config_path)
    assert_config_contains_expected_values(
        key_name,
        scheduler,
        os,
        instance,
        region,
        vpc_stack.cfn_outputs["PublicSubnetId"],
        vpc_stack.cfn_outputs["PrivateSubnetId"],
        config_path,
    )

    inject_additional_config_settings(config_path, request, region)
    clusters_factory(config_path)


def test_pcluster_configure_avoid_bad_subnets(
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
    stages = orchestrate_pcluster_configure_stages(
        region,
        key_name,
        scheduler,
        os,
        instance,
        vpc_stack.cfn_outputs["VpcId"],
        # This test does not provide head_node/compute_subnet_ids input.
        # Therefore, pcluster configure should use the subnet specified in the config file by default.
        # However, in this test, the availability zone of the subnet in the config file does not contain c5.xlarge.
        # Eventually, pcluster configure should omit the subnet in the config file
        # and use the first subnet in the remaining list of subnets
        "",
        "",
        omitted_subnets_num=1,
    )
    assert_configure_workflow(region, stages, config_path)
    assert_config_contains_expected_values(key_name, scheduler, os, instance, region, None, None, config_path)


def test_region_without_t2micro(vpc_stack, pcluster_config_reader, key_name, region, os, scheduler, test_datadir):
    """
    Verify the default instance type (free tier) is retrieved dynamically according to region.
    In other words, t3.micro is retrieved when the region does not contain t2.micro
    """
    config_path = test_datadir / "config.yaml"
    stages = orchestrate_pcluster_configure_stages(
        region,
        key_name,
        scheduler,
        os,
        "",
        vpc_stack.cfn_outputs["VpcId"],
        vpc_stack.cfn_outputs["PublicSubnetId"],
        vpc_stack.cfn_outputs["PrivateSubnetId"],
    )
    assert_configure_workflow(region, stages, config_path)
    assert_config_contains_expected_values(
        key_name,
        scheduler,
        os,
        "",
        region,
        vpc_stack.cfn_outputs["PublicSubnetId"],
        vpc_stack.cfn_outputs["PrivateSubnetId"],
        config_path,
    )


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


def assert_configure_workflow(region, stages, config_path):
    logging.info(f"Using `pcluster configure` to write a configuration to {config_path}")
    environ["AWS_DEFAULT_REGION"] = region
    configure_process = pexpect.spawn(f"pcluster configure --config {config_path}")
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
    key_name, scheduler, os, instance, region, head_node_subnet_id, compute_subnet_id, config_path
):
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
                "parameter_path": ["Scheduling", "SlurmQueues", 0, "ComputeResources", 0, "InstanceType"],
                "expected_value": instance,
            },
            {
                "parameter_path": ["Scheduling", "SlurmQueues", 0, "ComputeResources", 0, "MinCount"],
                "expected_value": 0,
            },
        ]
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
        if not expected_value:
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


def orchestrate_pcluster_configure_stages(
    region, key_name, scheduler, os, instance, vpc_id, head_node_subnet_id, compute_subnet_id, omitted_subnets_num=0
):
    size_name = "vCPU" if scheduler == "awsbatch" else "instance count"
    # Default compute subnet follows the selection of head node subnet
    default_compute_subnet = head_node_subnet_id or "subnet-.+"
    # When there are omitted subnets, a note should be printed
    omitted_note = "Note: {0} subnet.+not listed.+".format(omitted_subnets_num) if omitted_subnets_num else ""
    stage_list = [
        {"prompt": r"AWS Region ID \[.*\]: ", "response": region},
        {"prompt": r"EC2 Key Pair Name \[.*\]: ", "response": key_name},
        {"prompt": r"Scheduler \[slurm\]: ", "response": scheduler},
        {"prompt": r"Operating System \[alinux2\]: ", "response": os, "skip_for_batch": True},
        {"prompt": r"Head node instance type \[t.\.micro\]: ", "response": instance},
        {"prompt": r"Number of queues \[1\]: ", "response": "1", "skip_for_batch": True},
        {"prompt": r"Name of queue 1 \[queue1\]: ", "response": "myqueue"},
        {"prompt": r"Number of compute resources for myqueue \[1\]: ", "response": "1", "skip_for_batch": True},
        {
            "prompt": r"Compute instance type for compute resource 1 in myqueue \[t.\.micro\]: ",
            "response": instance,
            "skip_for_batch": True,
        },
        {"prompt": rf"Maximum {size_name} \[10\]: ", "response": ""},
        {"prompt": r"Automate VPC creation\? \(y/n\) \[n\]: ", "response": "n"},
        {"prompt": r"VPC ID \[vpc-.+\]: ", "response": vpc_id},
        {"prompt": r"Automate Subnet creation\? \(y/n\) \[y\]: ", "response": "n"},
        {"prompt": rf"{omitted_note}head node subnet ID \[subnet-.+\]: ", "response": head_node_subnet_id},
        {"prompt": rf"{omitted_note}compute subnet ID \[{default_compute_subnet}\]: ", "response": compute_subnet_id},
    ]
    # When a user selects Batch as the scheduler, pcluster configure does not prompt for OS or compute instance type.
    return [stage for stage in stage_list if scheduler != "awsbatch" or not stage.get("skip_for_batch")]


@pytest.fixture()
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
        AvailabilityZoneId="use1-az3", CidrBlock="192.168.0.0/21", VpcId=vpc_stack.cfn_outputs["VpcId"]
    )["Subnet"]["SubnetId"]
    yield subnet_id
    ec2_client.delete_subnet(SubnetId=subnet_id)
