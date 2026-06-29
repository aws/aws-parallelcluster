# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from datetime import datetime, timedelta, timezone

import boto3
import pytest
import xmltodict
from assertpy import assert_that, soft_assertions
from remote_command_executor import RemoteCommandExecutor
from utils import get_compute_nodes_instance_ids, get_instance_info

from tests.common.assertions import assert_no_errors_in_logs
from tests.common.mpi_common import _test_mpi
from tests.common.nccl_common import install_and_run_nccl_benchmarks
from tests.common.utils import (
    fetch_instance_slots,
    get_capacity_reservation_id,
    read_remote_file,
    run_system_analyzer,
    wait_process_completion,
)

# Candidate head node instance types for when compute is p* or hpc* (one per family).
HEAD_NODE_CANDIDATES_X86 = [
    "c5.18xlarge",
    "c6i.16xlarge",
    "c7i.16xlarge",
    "m5.16xlarge",
    "m6i.16xlarge",
    "m7i.16xlarge",
    "r5.16xlarge",
]
HEAD_NODE_CANDIDATES_ARM = [
    "c6g.16xlarge",
    "c7g.16xlarge",
    "m6g.16xlarge",
    "m7g.16xlarge",
    "r6g.16xlarge",
]

FABTESTS_BASIC_TESTS = ["rdm_tagged_bw", "rdm_tagged_pingpong"]

FABTESTS_GDRCOPY_TESTS = ["runt"]


def _try_reserve_head_node_instance(region, az_id, architecture, os):
    """Try to create a 1-hour capacity reservation for a head node instance in the given AZ.

    Iterates through candidate instance types (one per family) and returns the first one that succeeds.
    Returns the selected instance type. Falls back to the first candidate if all reservations fail.
    """
    ec2_client = boto3.client("ec2", region_name=region)
    candidates = HEAD_NODE_CANDIDATES_X86 if architecture == "x86_64" else HEAD_NODE_CANDIDATES_ARM
    instance_platform = "Red Hat Enterprise Linux" if "rhel" in os else "Linux/UNIX"
    end_date = datetime.now(timezone.utc) + timedelta(hours=1)

    for candidate in candidates:
        try:
            response = ec2_client.create_capacity_reservation(
                InstanceType=candidate,
                InstancePlatform=instance_platform,
                AvailabilityZoneId=az_id,
                InstanceCount=1,
                EndDateType="limited",
                EndDate=end_date,
                Tenancy="default",
            )
            cr_id = response["CapacityReservation"]["CapacityReservationId"]
            logging.info("Created head node capacity reservation %s for %s in %s", cr_id, candidate, az_id)
            return candidate
        except Exception as e:
            logging.info("Capacity reservation for head node %s failed in %s: %s", candidate, az_id, e)

    # All candidates failed
    pytest.fail(
        "Could not reserve capacity for any head node instance type candidate",
    )
    return None


@pytest.mark.usefixtures("flags")
def test_efa(
    os,
    region,
    scheduler,
    instance,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    architecture,
    scheduler_commands_factory,
    request,
    vpc_stack,
):
    """
    Test all EFA Features.

    Grouped all tests in a single function so that cluster can be reused for all of them.
    """
    head_node_instance = instance
    if len(get_instance_info(instance, region)["NetworkInfo"]["NetworkCards"]) > 1:
        az_id = vpc_stack.az_override or vpc_stack.default_az_id
        head_node_instance = _try_reserve_head_node_instance(region, az_id, architecture, os)
    max_queue_size = 2
    capacity_reservation_id = None
    # p6 family instances need capacity blocks and so placement group is set to false
    capacity_block_instance_type = instance.startswith("p6")
    placement_group_enabled = not capacity_block_instance_type
    if capacity_block_instance_type:
        capacity_reservations_ids = get_capacity_reservation_id(request, instance, region, max_queue_size, os)
        if capacity_reservations_ids:
            capacity_reservation_id = capacity_reservations_ids[0].get("CapacityReservationId")
        else:
            message = f"Skipping the test as no Capacity Block for {instance} and os {os} was found in {region}"
            logging.warn(message)
            pytest.skip(message)

    slots_per_instance = fetch_instance_slots(region, instance, multithreading_disabled=True)
    cluster_config = pcluster_config_reader(
        head_node_instance=head_node_instance,
        max_queue_size=max_queue_size,
        capacity_reservation_id=capacity_reservation_id,
        placement_group_enabled=placement_group_enabled,
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    _test_efa_installation(scheduler_commands, remote_command_executor, efa_installed=True, partition="efa-enabled")
    _test_efa_eni_configuration(cluster, region)
    _test_mpi(remote_command_executor, slots_per_instance, scheduler, scheduler_commands, partition="efa-enabled")
    logging.info("Running on Instances: {0}".format(get_compute_nodes_instance_ids(cluster.cfn_name, region)))

    run_system_analyzer(cluster, scheduler_commands_factory, request, partition="efa-enabled")

    _test_shm_transfer_is_enabled(scheduler_commands, remote_command_executor, partition="efa-enabled")

    if instance.startswith("p"):
        # Doc of supported instance types and operating systems:
        # https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start-nccl.html
        install_and_run_nccl_benchmarks(remote_command_executor, "openmpi", scheduler_commands, instance, os)

    with soft_assertions():
        assert_no_errors_in_logs(remote_command_executor, scheduler, skip_ice=True)
    if "us-iso" not in region:
        # Run Fabric tests. Fabric tests require Internet connection, so cannot be run in us-iso regions
        run_system_analyzer(cluster, scheduler_commands_factory, request, partition="efa-enabled")

        fabtests_report = _execute_fabtests(remote_command_executor, test_datadir, instance)

        num_tests = int(fabtests_report.get("testsuites", {}).get("testsuite", {})[0].get("@tests", None))
        num_failures = int(fabtests_report.get("testsuites", {}).get("testsuite", {})[0].get("@failures", None))
        num_errors = int(fabtests_report.get("testsuites", {}).get("testsuite", {})[0].get("@errors", None))

        with soft_assertions():
            assert_that(num_tests, description="Cannot read number of tests from Fabtests report").is_not_none()
            assert_that(num_failures, description="Cannot read number of failures from Fabtests report").is_not_none()
            assert_that(num_errors, description="Cannot read number of errors from Fabtests report").is_not_none()

        if num_failures + num_errors > 0:
            logging.info(f"Fabtests report:\n{fabtests_report}")

        with soft_assertions():
            assert_that(
                num_failures, description=f"{num_failures}/{num_tests} libfabric tests are failing"
            ).is_equal_to(0)
            assert_that(num_errors, description=f"{num_errors}/{num_tests} libfabric tests got errors").is_equal_to(0)
            assert_no_errors_in_logs(remote_command_executor, scheduler, skip_ice=True)


def _test_efa_eni_configuration(cluster, region):
    """Verify compute nodes have the expected EFA network interface configuration.

    Under the new default (PC 3.15):
    - Each compute node should have exactly one private IP address (on the interface ENI at NCI-0)
    - All ENIs except one should be efa-only (no IP, EFA fabric only)
    """
    ec2_client = boto3.client("ec2", region_name=region)
    compute_instance_ids = get_compute_nodes_instance_ids(cluster.cfn_name, region)

    for instance_id in compute_instance_ids:
        instance_info = ec2_client.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]
        enis = instance_info["NetworkInterfaces"]
        logging.info(f"Instance {instance_id} has {len(enis)} ENIs")

        enis_with_ip = []
        efa_only_enis = []
        for eni in enis:
            interface_type = eni.get("InterfaceType", "interface")
            private_ips = eni.get("PrivateIpAddresses", [])
            attachment = eni.get("Attachment", {})
            network_card_index = attachment.get("NetworkCardIndex", 0)
            device_index = attachment.get("DeviceIndex", 0)
            logging.info(
                f"  ENI {eni['NetworkInterfaceId']}: InterfaceType={interface_type}, "
                f"PrivateIPs={len(private_ips)}, NetworkCardIndex={network_card_index}, DeviceIndex={device_index}"
            )
            if interface_type == "efa-only":
                efa_only_enis.append(eni)
            else:
                enis_with_ip.append(eni)

        # Exactly one ENI should have a private IP (the interface ENI on NCI-0)
        assert_that(
            len(enis_with_ip), description=f"Instance {instance_id} should have exactly 1 ENI with a private IP"
        ).is_equal_to(1)

        # All other ENIs should be efa-only
        if len(enis) > 1:
            assert_that(
                len(efa_only_enis), description=f"Instance {instance_id}: all ENIs except one should be efa-only"
            ).is_equal_to(len(enis) - 1)

        logging.info(
            f"Instance {instance_id}: {len(enis_with_ip)} ENI(s) with private IP, {len(efa_only_enis)} efa-only ENI(s)"
        )


def _execute_fabtests(remote_command_executor, test_datadir, instance):
    fabtests_dir = "/shared/fabtests"
    fabtests_pid_file = f"{fabtests_dir}/outputs/fabtests.pid"
    fabtests_log_file = f"{fabtests_dir}/outputs/fabtests.log"
    fabtests_report_file = f"{fabtests_dir}/outputs/fabtests.report"

    logging.info("Installing Fabtests")
    remote_command_executor.run_remote_script(
        str(test_datadir / "install-fabtests.sh"), args=[fabtests_dir], timeout=600
    )

    logging.info("Running Fabtests")
    test_cases = FABTESTS_BASIC_TESTS + FABTESTS_GDRCOPY_TESTS if instance == "p4d.24xlarge" else FABTESTS_BASIC_TESTS

    if "g6" in instance:
        test_cases = test_cases + ["not cuda"]

    remote_command_executor.run_remote_script(
        str(test_datadir / "run-fabtests.sh"),
        args=[
            fabtests_dir,
            fabtests_pid_file,
            fabtests_log_file,
            fabtests_report_file,
            "efa-enabled-st-efa-enabled-i1-1",
            "efa-enabled-st-efa-enabled-i1-2",
            ",".join(test_cases),
            "enable-gdr" if instance == "p4d.24xlarge" else "skip-gdr",
        ],
        timeout=60,
        pty=False,
    )

    pid = read_remote_file(remote_command_executor, fabtests_pid_file)

    wait_process_completion(remote_command_executor, pid)

    logging.info("Retrieving Fabtests report")
    report_content = read_remote_file(remote_command_executor, fabtests_report_file)
    logging.info("Parsing Fabtests report")
    return xmltodict.parse(report_content)


def _test_efa_installation(scheduler_commands, remote_command_executor, efa_installed=True, partition=None):
    # Output contains:
    # 00:06.0 Ethernet controller: Amazon.com, Inc. Device efa0
    logging.info("Testing EFA installed")
    if partition:
        result = scheduler_commands.submit_command("lspci -n > /shared/lspci.out", partition=partition)
    else:
        result = scheduler_commands.submit_command("lspci -n > /shared/lspci.out")

    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)

    # Check if EFA interface is on compute node
    result = remote_command_executor.run_remote_command("cat /shared/lspci.out")
    if efa_installed:
        assert_that(result.stdout).contains("1d0f:efa")
    else:
        assert_that(result.stdout).does_not_contain("1d0f:efa")

    # Check EFA interface not present on head node
    result = remote_command_executor.run_remote_command("lspci -n")
    assert_that(result.stdout).does_not_contain("1d0f:efa")


def _test_shm_transfer_is_enabled(scheduler_commands, remote_command_executor, partition=None):
    logging.info("Testing SHM Transfer is enabled")
    if partition:
        result = scheduler_commands.submit_command("fi_info -p efa 2>&1 > /shared/fi_info.out", partition=partition)
    else:
        result = scheduler_commands.submit_command("fi_info -p efa 2>&1 > /shared/fi_info.out")
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    job_stdout = remote_command_executor.run_remote_command(f"cat slurm-{job_id}.out").stdout
    logging.info(f"Job stdout is: {job_stdout}")
    scheduler_commands.assert_job_succeeded(job_id)
    result = remote_command_executor.run_remote_command("cat /shared/fi_info.out")
    assert_that(result.stdout).does_not_contain("SHM transfer will be disabled because of ptrace protection")
