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
import configparser
import pexpect
import pytest
from assertpy import assert_that
from conftest import add_custom_packages_configs


@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["c5.xlarge", "m6g.xlarge"])
@pytest.mark.schedulers(["awsbatch", "slurm", "sge"])
# Do not run on ARM + Batch
# pcluster configure always picks optimal and Batch does not support ARM for optimal for now
@pytest.mark.skip_dimensions("*", "m6g.xlarge", "*", "awsbatch")
def test_pcluster_configure(
    request, vpc_stack, key_name, region, os, instance, scheduler, clusters_factory, test_datadir
):
    """Verify that the config file produced by `pcluster configure` can be used to create a cluster."""
    skip_if_unsupported_test_options_were_used(request)
    config_path = test_datadir / "config.ini"
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
        region,
        key_name,
        scheduler,
        os,
        instance,
        vpc_stack.cfn_outputs["VpcId"],
        vpc_stack.cfn_outputs["PublicSubnetId"],
        vpc_stack.cfn_outputs["PrivateSubnetId"],
        config_path,
    )

    add_custom_packages_configs(config_path, request, region)
    clusters_factory(config_path)


@pytest.mark.dimensions("us-east-1", "c5.xlarge", "alinux2", "slurm")
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
    can correct the headnode/compute_subnet_id fields using qualified subnets and show a message for the omitted subnets
    """
    config_path = pcluster_config_reader(wrong_subnet_id=subnet_in_use1_az3)
    stages = orchestrate_pcluster_configure_stages(
        region,
        key_name,
        scheduler,
        os,
        instance,
        vpc_stack.cfn_outputs["VpcId"],
        # This test does not provide headnode/compute_subnet_ids input.
        # Therefore, pcluster configure should use the subnet specified in the config file by default.
        # However, in this test, the availability zone of the subnet in the config file does not contain c5.xlarge.
        # Eventually, pcluster configure should omit the subnet in the config file
        # and use the first subnet in the remaining list of subnets
        "",
        "",
        omitted_subnets_num=1,
    )
    assert_configure_workflow(region, stages, config_path)
    assert_config_contains_expected_values(
        region,
        key_name,
        scheduler,
        os,
        instance,
        vpc_stack.cfn_outputs["VpcId"],
        None,
        None,
        config_path,
    )


def test_region_without_t2micro(
    vpc_stack,
    pcluster_config_reader,
    key_name,
    region,
    os,
    scheduler,
    test_datadir,
):
    """
    Verify the default instance type (free tier) is retrieved dynamically according to region.
    In other words, t3.micro is retrieved when the region does not contain t2.micro
    """
    config_path = test_datadir / "config.ini"
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
        region,
        key_name,
        scheduler,
        os,
        "",
        vpc_stack.cfn_outputs["VpcId"],
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
    configure_process = pexpect.spawn(f"pcluster configure -c {config_path}")
    for stage in stages:
        configure_prompt_status = configure_process.expect(stage.get("prompt"))
        assert_that(configure_prompt_status).is_equal_to(0)
        configure_process.sendline(stage.get("response"))

    # Expecting EOF verifies that `pcluster configure` finished as expected.
    configure_process.expect(pexpect.EOF)
    configure_process.close()
    assert_that(configure_process.exitstatus).is_equal_to(0)

    # Log the generated config's contents so debugging doesn't always require digging through Jenkins artifacts
    with open(config_path) as config_file:
        logging.info(f"Configuration file generated by `pcluster configure`\n{config_file.read()}")


def assert_config_contains_expected_values(
    region, key_name, scheduler, os, instance, vpc_id, headnode_subnet_id, compute_subnet_id, config_path
):
    config = configparser.ConfigParser()
    config.read(config_path)

    # Assert that the config object contains the expected values
    param_validators = [
        {"section_name": "aws", "parameter_name": "aws_region_name", "expected_value": region},
        {"section_name": "cluster default", "parameter_name": "key_name", "expected_value": key_name},
        {"section_name": "cluster default", "parameter_name": "scheduler", "expected_value": scheduler},
        {
            "section_name": "cluster default",
            "parameter_name": "base_os",
            "expected_value": os if scheduler != "awsbatch" else "alinux2",
        },
        {"section_name": "cluster default", "parameter_name": "master_instance_type", "expected_value": instance},
        {"section_name": "vpc default", "parameter_name": "vpc_id", "expected_value": vpc_id},
        {"section_name": "vpc default", "parameter_name": "master_subnet_id", "expected_value": headnode_subnet_id},
        {"section_name": "vpc default", "parameter_name": "compute_subnet_id", "expected_value": compute_subnet_id},
    ]

    if scheduler == "slurm":
        param_validators += [
            {"section_name": "cluster default", "parameter_name": "queue_settings", "expected_value": "compute"},
            {
                "section_name": "queue compute",
                "parameter_name": "compute_resource_settings",
                "expected_value": "default",
            },
            {"section_name": "compute_resource default", "parameter_name": "instance_type", "expected_value": instance},
            {"section_name": "compute_resource default", "parameter_name": "min_count", "expected_value": 1},
        ]
    elif scheduler == "awsbatch":
        param_validators += [
            {"section_name": "cluster default", "parameter_name": "min_vcpus", "expected_value": 1},
            {"section_name": "cluster default", "parameter_name": "desired_vcpus", "expected_value": 1},
        ]
    else:
        param_validators += [
            {"section_name": "cluster default", "parameter_name": "initial_queue_size", "expected_value": 1},
            {"section_name": "cluster default", "parameter_name": "maintain_initial_size", "expected_value": "true"},
            {"section_name": "cluster default", "parameter_name": "compute_instance_type", "expected_value": instance},
        ]

    for validator in param_validators:
        expected_value = validator.get("expected_value")
        if not expected_value:
            # if expected_value is empty, skip the assertion.
            continue
        observed_value = config[validator.get("section_name")][validator.get("parameter_name")]
        assert_that(observed_value).is_equal_to(str(expected_value))


def orchestrate_pcluster_configure_stages(
    region,
    key_name,
    scheduler,
    os,
    instance,
    vpc_id,
    headnode_subnet_id,
    compute_subnet_id,
    omitted_subnets_num=0,
):
    compute_units = "vcpus" if scheduler == "awsbatch" else "instances"
    # Default compute subnet follows the selection of headnode subnet
    default_compute_subnet = headnode_subnet_id if headnode_subnet_id else "subnet-.+"
    # When there are omitted subnets, a note should be printed
    omitted_note = "Note:  {0} subnet.+not listed.+".format(omitted_subnets_num) if omitted_subnets_num else ""
    stage_list = [
        {"prompt": r"AWS Region ID \[.*\]: ", "response": region},
        {"prompt": r"EC2 Key Pair Name \[.*\]: ", "response": key_name},
        {"prompt": r"Scheduler \[slurm\]: ", "response": scheduler},
        {"prompt": r"Operating System \[alinux2\]: ", "response": os, "skip_for_batch": True},
        {"prompt": fr"Minimum cluster size \({compute_units}\) \[0\]: ", "response": "1"},
        {"prompt": fr"Maximum cluster size \({compute_units}\) \[10\]: ", "response": ""},
        {"prompt": r"Head node instance type \[t.\.micro\]: ", "response": instance},
        {"prompt": r"Compute instance type \[t.\.micro\]: ", "response": instance, "skip_for_batch": True},
        {"prompt": r"Automate VPC creation\? \(y/n\) \[n\]: ", "response": "n"},
        {"prompt": r"VPC ID \[vpc-.+\]: ", "response": vpc_id},
        {"prompt": r"Automate Subnet creation\? \(y/n\) \[y\]: ", "response": "n"},
        {
            "prompt": fr"{omitted_note}head node Subnet ID \[subnet-.+\]: ",
            "response": headnode_subnet_id,
        },
        {
            "prompt": fr"{omitted_note}compute Subnet ID \[{default_compute_subnet}\]: ",
            "response": compute_subnet_id,
        },
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
        Filters=[
            {"Name": "instance-type", "Values": ["c5.xlarge"]},
            {"Name": "location", "Values": ["use1-az3"]},
        ],
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
        AvailabilityZoneId="use1-az3", CidrBlock="192.168.16.0/20", VpcId=vpc_stack.cfn_outputs["VpcId"]
    )["Subnet"]["SubnetId"]
    yield subnet_id
    ec2_client.delete_subnet(SubnetId=subnet_id)
