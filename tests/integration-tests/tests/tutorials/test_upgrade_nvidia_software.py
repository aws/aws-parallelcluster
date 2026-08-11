# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import time

import boto3
import pytest
import yaml
from assertpy import assert_that, soft_assertions
from jinja2 import DebugUndefined
from jinja2.sandbox import SandboxedEnvironment
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from utils import generate_stack_name

from tests.common.assertions import assert_head_node_is_running
from tests.common.utils import (
    generate_random_string,
    get_installed_parallelcluster_base_version,
    retrieve_latest_ami,
    run_gpu_workload,
)

# Instance types: build on a GPU instance so the NVIDIA driver installation is exercised on GPU
# hardware; the head node validates that the upgraded AMI boots on non-GPU instances too. The GPU
# compute node type comes from the `instance` dimension.
BUILD_INSTANCE_TYPE = "g4dn.2xlarge"
HEAD_NODE_INSTANCE_TYPE = "c5.xlarge"

QUEUE_NAME = "q1"
COMPUTE_RESOURCE_NAME = "cr1"

# Software versions installed by the component. The test injects these values into the AWSTOE
# constants of the component document (placeholder markers in update-nvidia.yaml) and
# asserts the same versions on the cluster nodes.
NVIDIA_DRIVER_VERSION = "595.71.05"
CUDA_VERSION = "13.2.2"
CUDA_SAMPLES_VERSION = "13.3"
CUDA_RELEASE_NVIDIA_VERSION = "595.71.05"
CUDA_RELEASE = ".".join(CUDA_VERSION.split(".")[:2])
NVLSM_BUNDLED_VERSION = "2025.10.12"

# Packages whose version must match the NVIDIA driver version exactly.
DRIVER_ALIGNED_PACKAGES = ["nvidia-fabricmanager", "nvidia-imex", "libnvsdm"]


@pytest.fixture()
def nvidia_stack_component(region, request):
    """Manage the creation/deletion of the EC2 Image Builder component with the NVIDIA upgrade procedure."""
    imagebuilder_client = boto3.client("imagebuilder", region_name=region)
    component_arn = None

    def _create_component(component_document):
        nonlocal component_arn
        # Random suffix to avoid name+version clashes across concurrent test runs in the same account/region.
        component_name = f"update-nvidia-{generate_random_string()}"
        logging.info("Creating Image Builder component %s", component_name)
        response = imagebuilder_client.create_component(
            name=component_name,
            semanticVersion="1.0.0",
            platform="Linux",
            data=component_document,
        )
        component_arn = response["componentBuildVersionArn"]
        logging.info("Created Image Builder component %s", component_arn)
        return component_arn

    yield _create_component

    if component_arn and not request.config.getoption("no_delete"):
        logging.info("Deleting Image Builder component %s", component_arn)
        imagebuilder_client.delete_component(componentBuildVersionArn=component_arn)
        logging.info("Deleted Image Builder component %s", component_arn)
    elif component_arn:
        logging.warning("Skipping deletion of Image Builder component %s because --no-delete is set", component_arn)


@pytest.mark.usefixtures("scheduler")
def test_upgrade_nvidia_software(
    region,
    os,
    instance,
    architecture,
    test_datadir,
    pcluster_config_reader,
    images_factory,
    clusters_factory,
    scheduler_commands_factory,
    nvidia_stack_component,
    request,
):
    """
    Validate the tutorial procedure to upgrade the NVIDIA software stack via a custom AMI.

    Steps:
    1. Create an EC2 Image Builder component with the NVIDIA upgrade procedure (driver + CUDA
       runfiles, NVLink stack from the NVIDIA driver local repository), injecting the expected
       software versions into the AWSTOE constants of the component document.
    2. Build a custom AMI with `pcluster build-image` using the official vanilla OS AMI as
       parent and the component from step 1.
    3. Wait for the AMI produced by the build to be available in EC2.
    4. Create a cluster using the custom AMI, with a static GPU compute node.
    5. Assert the NVIDIA software versions (driver, CUDA, Fabric Manager, IMEX, libnvsdm, NVLSM)
       on the GPU compute node are the ones installed by the component.
    6. Run a GPU workload through the scheduler, reusing the shared CUDA samples job script
       (tests/common/data/gpu_job.sh), and assert it succeeds.
    7. Teardown is managed by the fixtures (cluster, image and Image Builder component).
    """
    # Step 1: render the component document, injecting the software versions into its AWSTOE
    # constants, and create the Image Builder component from it.
    logging.info("Expecting NVIDIA driver %s and CUDA release %s", NVIDIA_DRIVER_VERSION, CUDA_RELEASE)
    component_document = _render_component_document(test_datadir, architecture)
    component_arn = nvidia_stack_component(component_document)

    # Step 2: build the custom AMI with pcluster build-image, using the official vanilla OS AMI
    # as parent image.
    parent_image = retrieve_latest_ami(region, os, ami_type="official", architecture=architecture)
    image_id = generate_stack_name("integ-tests-upgrade-nvidia", request.config.getoption("stackname_suffix"))
    image_config = pcluster_config_reader(
        config_file="image.config.yaml",
        parent_image=parent_image,
        component_arn=component_arn,
        build_instance_type=BUILD_INSTANCE_TYPE,
    )
    image = images_factory(image_id, image_config, region)
    _wait_for_build_image_complete(image)

    # Step 3: the build produced an AMI; wait for it to be available in EC2.
    assert_that(image.ec2_image_id).described_as("EC2 AMI id from the image build").is_not_none()
    _wait_for_ami_available(region, image.ec2_image_id)

    # Step 4: create a cluster using the custom AMI.
    cluster_config = pcluster_config_reader(
        custom_ami=image.ec2_image_id,
        head_node_instance_type=HEAD_NODE_INSTANCE_TYPE,
        queue_name=QUEUE_NAME,
        compute_resource_name=COMPUTE_RESOURCE_NAME,
    )
    cluster = clusters_factory(cluster_config)
    assert_head_node_is_running(region, cluster)

    # Step 5: assert the NVIDIA software versions on the GPU compute node.
    compute_node_ip = cluster.get_compute_nodes_private_ip(QUEUE_NAME, COMPUTE_RESOURCE_NAME)[0]
    compute_remote_command_executor = RemoteCommandExecutor(cluster, compute_node_ip=compute_node_ip)
    _assert_nvidia_stack_versions(compute_remote_command_executor, NVIDIA_DRIVER_VERSION, CUDA_RELEASE)

    # Step 6: run a GPU workload through the scheduler and assert it succeeds.
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    run_gpu_workload(scheduler_commands, partition=QUEUE_NAME)

    # Step 7: teardown is managed by clusters_factory, images_factory and nvidia_stack_component.


def _render_component_document(test_datadir, architecture):
    """
    Render the component document template, injecting the software versions into its constants.

    The template is the tutorial component document with lowercase jinja variables as the values
    of its AWSTOE constants section; every other line is identical to the tutorial document.
    Injecting the values here keeps the test as the single source of truth for the expected
    versions, instead of parsing them back out of the component.

    The jinja environment uses DebugUndefined so that the uppercase AWSTOE constant references
    used by the document steps ("{{ NVIDIA_DRIVER_VERSION }}"), being undefined jinja variables,
    are re-emitted verbatim instead of blanked: they must reach Image Builder untouched, since
    AWSTOE resolves them at build time.
    """
    expected_constants = {
        "NVIDIA_DRIVER_VERSION": NVIDIA_DRIVER_VERSION,
        # The NVIDIA installers use "aarch64" for arm64.
        "ARCH": {"x86_64": "x86_64", "arm64": "aarch64"}[architecture],
        "CUDA_VERSION": CUDA_VERSION,
        "CUDA_SAMPLES_VERSION": CUDA_SAMPLES_VERSION,
        "CUDA_RELEASE_NVIDIA_VERSION": CUDA_RELEASE_NVIDIA_VERSION,
    }
    template = SandboxedEnvironment(undefined=DebugUndefined).from_string(
        (test_datadir / "update-nvidia.yaml").read_text()
    )
    document = template.render(**{name.lower(): value for name, value in expected_constants.items()})

    # Guard: the constants of the rendered document must carry exactly the injected values
    # (catches blanked or misnamed jinja variables).
    rendered_constants = {
        name: attrs["value"] for item in yaml.safe_load(document).get("constants", []) for name, attrs in item.items()
    }
    assert_that(rendered_constants).described_as("rendered component constants").is_equal_to(expected_constants)
    return document


def _wait_for_build_image_complete(image):
    """Wait for the image build to complete and assert it succeeded."""
    logging.info("Waiting for build of image %s to complete", image.image_id)
    while image.image_status.endswith("_IN_PROGRESS"):  # e.g. BUILD_IN_PROGRESS
        time.sleep(300)
        logging.info(image.describe())
    if image.image_status != "BUILD_COMPLETE":
        _log_recent_image_build_events(image)
    assert_that(image.image_status).is_equal_to("BUILD_COMPLETE")


def _log_recent_image_build_events(image):
    """Log the last lines of the image build log to ease troubleshooting of a failed build."""
    log_stream_name = f"{get_installed_parallelcluster_base_version()}/1"
    nlines = 200
    try:
        log_events = image.get_log_events(log_stream_name, start_from_head=False, query="events[*]", limit=nlines)
        log_messages = [event["message"] for event in log_events]
        logging.error(
            "Image build failed for %s, the last %d lines of the log are:\n%s",
            image.image_id,
            nlines,
            "\n".join(log_messages),
        )
    except Exception as e:  # noqa: BLE001
        logging.error("Could not retrieve build log events for image %s: %s", image.image_id, e)


@retry(
    retry_on_result=lambda state: state != "available",
    wait_fixed=seconds(30),
    stop_max_delay=minutes(15),
)
def _wait_for_ami_available(region, ec2_image_id):
    """Wait for the AMI produced by the build to reach the "available" state in EC2."""
    images = boto3.client("ec2", region_name=region).describe_images(ImageIds=[ec2_image_id]).get("Images")
    state = images[0]["State"] if images else None
    logging.info("AMI %s state: %s", ec2_image_id, state)
    return state


def _assert_nvidia_stack_versions(remote_command_executor, driver_version, cuda_release):
    """Assert driver, CUDA and NVLink stack versions on the node (must run on a GPU node)."""

    def _run(command):
        return remote_command_executor.run_remote_command(command).stdout.strip()

    with soft_assertions():
        # NVIDIA driver: both the installed kernel module and the one loaded by the running GPU.
        assert_that(_run("modinfo -F version nvidia")).described_as("installed nvidia kernel module").is_equal_to(
            driver_version
        )
        assert_that(_run("nvidia-smi --query-gpu=driver_version --format=csv,noheader")).described_as(
            "driver loaded by nvidia-smi"
        ).is_equal_to(driver_version)

        # CUDA toolkit.
        assert_that(_run("/usr/local/cuda/bin/nvcc --version")).described_as("nvcc release").contains(
            f"release {cuda_release}"
        )

        # NVLink software stack: Fabric Manager, IMEX and libnvsdm must match the driver version
        # exactly; NVLSM is installed at the version bundled in the driver local repository.
        for package in DRIVER_ALIGNED_PACKAGES:
            assert_that(_run(f"rpm -q --qf '%{{VERSION}}' {package}")).described_as(package).is_equal_to(driver_version)
        assert_that(_run("rpm -q --qf '%{VERSION}' nvlsm")).described_as("nvlsm").is_equal_to(NVLSM_BUNDLED_VERSION)
