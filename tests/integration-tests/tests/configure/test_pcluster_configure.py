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

import pexpect
import pytest
from assertpy import assert_that
from conftest import add_custom_packages_configs

from pcluster.config.pcluster_config import PclusterConfig


@pytest.mark.regions(["us-east-1"])
@pytest.mark.instances(["c5.xlarge", "m6g.xlarge"])
@pytest.mark.schedulers(["awsbatch", "slurm", "sge"])
# Do not run on ARM + Batch
# pcluster configure always picks optimal and Batch does not support ARM for optimal for now
@pytest.mark.skip_dimensions("*", "m6g.xlarge", "*", "awsbatch")
def test_pcluster_configure(
    request, vpc_stack, key_name, region, os, instance, scheduler, clusters_factory, test_datadir
):
    """Verify that the configuration file produced by `pcluster configure` can be used to create a cluster."""
    skip_if_unsupported_test_options_were_used(request)
    config_path = test_datadir / "config.ini"
    orchestrate_pcluster_configure(
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


def orchestrate_pcluster_configure(
    region, key_name, scheduler, os, instance, vpc_id, public_subnet_id, private_subnet_id, config_path
):
    compute_units = "vcpus" if scheduler == "awsbatch" else "instances"
    stages = [
        {"prompt": r"AWS Region ID \[.*\]: ", "response": region},
        {"prompt": r"EC2 Key Pair Name \[.*\]: ", "response": key_name},
        {"prompt": r"Scheduler \[slurm\]: ", "response": scheduler},
        {"prompt": r"Operating System \[alinux2\]: ", "response": os, "skip_for_batch": True},
        {"prompt": fr"Minimum cluster size \({compute_units}\) \[0\]: ", "response": "1"},
        {"prompt": fr"Maximum cluster size \({compute_units}\) \[10\]: ", "response": ""},
        {"prompt": r"Master instance type \[t2\.micro\]: ", "response": instance},
        {"prompt": r"Compute instance type \[t2\.micro\]: ", "response": instance, "skip_for_batch": True},
        {"prompt": r"Automate VPC creation\? \(y/n\) \[n\]: ", "response": "n"},
        {"prompt": r"VPC ID \[vpc-.+\]: ", "response": vpc_id},
        {"prompt": r"Automate Subnet creation\? \(y/n\) \[y\]: ", "response": "n"},
        {"prompt": r"Master Subnet ID \[subnet-.+\]: ", "response": public_subnet_id},
        {"prompt": fr"Compute Subnet ID \[{public_subnet_id}\]: ", "response": private_subnet_id},
    ]
    logging.info(f"Using `pcluster configure` to write a configuration to {config_path}")
    configure_process = pexpect.spawn(f"pcluster configure -c {config_path}")
    for stage in stages:
        if scheduler == "awsbatch" and stage.get("skip_for_batch"):
            # When a user selects Batch as the scheduler, pcluster configure does not prompt
            # for OS or compute instance type.
            continue
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
    region, key_name, scheduler, os, instance, vpc_id, public_subnet_id, private_subnet_id, config_path
):
    pcluster_config = PclusterConfig(config_file=config_path, fail_on_file_absence=True, fail_on_error=True)

    # Assert that the config is valid
    pcluster_config.validate()

    # Assert that the config object contains the expected values
    param_validators = [
        {"section_name": "aws", "parameter_name": "aws_region_name", "expected_value": region},
        {"section_name": "cluster", "parameter_name": "key_name", "expected_value": key_name},
        {"section_name": "cluster", "parameter_name": "scheduler", "expected_value": scheduler},
        {
            "section_name": "cluster",
            "parameter_name": "base_os",
            "expected_value": os if scheduler != "awsbatch" else "alinux2",
        },
        {"section_name": "cluster", "parameter_name": "master_instance_type", "expected_value": instance},
        {"section_name": "vpc", "parameter_name": "vpc_id", "expected_value": vpc_id},
        {"section_name": "vpc", "parameter_name": "master_subnet_id", "expected_value": public_subnet_id},
        {"section_name": "vpc", "parameter_name": "compute_subnet_id", "expected_value": private_subnet_id},
    ]

    if scheduler == "slurm":
        param_validators += [
            {"section_name": "cluster", "parameter_name": "queue_settings", "expected_value": "compute"},
            {"section_name": "queue", "parameter_name": "compute_resource_settings", "expected_value": "default"},
            {"section_name": "compute_resource", "parameter_name": "instance_type", "expected_value": instance},
            {"section_name": "compute_resource", "parameter_name": "min_count", "expected_value": 1},
        ]
    elif scheduler == "awsbatch":
        param_validators += [
            {"section_name": "cluster", "parameter_name": "min_vcpus", "expected_value": 1},
            {"section_name": "cluster", "parameter_name": "desired_vcpus", "expected_value": 1},
        ]
    else:
        param_validators += [
            {"section_name": "cluster", "parameter_name": "initial_queue_size", "expected_value": 1},
            {"section_name": "cluster", "parameter_name": "maintain_initial_size", "expected_value": True},
            {"section_name": "cluster", "parameter_name": "compute_instance_type", "expected_value": instance},
        ]

    for validator in param_validators:
        observed_value = pcluster_config.get_section(validator.get("section_name")).get_param_value(
            validator.get("parameter_name")
        )
        assert_that(observed_value).is_equal_to(validator.get("expected_value"))
