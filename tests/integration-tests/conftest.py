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

# This file has a special meaning for pytest. See https://docs.pytest.org/en/2.7.3/plugins.html for
# additional details.

import copy
import json
import logging
import os
import re
import time
from functools import partial
from itertools import product
from shutil import copyfile
from traceback import format_tb
from typing import Any, Dict, List, Optional, Union

import boto3
import pytest
import yaml
from _pytest.fixtures import FixtureDef, SubRequest
from cfn_stacks_factory import CfnStack, CfnStacksFactory, CfnVpcStack
from clusters_factory import Cluster, ClustersFactory
from conftest_markers import (
    DIMENSIONS_MARKER_ARGS,
    add_default_markers,
    check_marker_dimensions,
    check_marker_list,
    check_marker_skip_dimensions,
    check_marker_skip_list,
)
from conftest_networking import unmarshal_az_override
from conftest_tests_config import apply_cli_dimensions_filtering, parametrize_from_config, remove_disabled_tests
from conftest_utils import add_filename_markers, get_reporting_region
from constants import SCHEDULERS_SUPPORTING_IMDS_SECURED, NodeType
from filelock import FileLock
from framework.credential_providers import aws_credential_provider, register_cli_credentials_for_region
from framework.fixture_utils import xdist_session_fixture
from framework.framework_constants import METADATA_TABLE
from framework.metadata_table_manager import MetadataTableManager
from framework.tests_configuration.config_renderer import read_config_file
from framework.tests_configuration.config_utils import get_all_regions
from images_factory import Image, ImagesFactory
from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment
from troposphere import Ref, Sub, Template, ec2, resourcegroups
from troposphere.ec2 import PlacementGroup
from troposphere.efs import AccessPoint as EFSAccessPoint
from troposphere.efs import FileSystem as EFSFileSystem
from troposphere.efs import MountTarget
from troposphere.fsx import (
    ClientConfigurations,
    FileSystem,
    NfsExports,
    StorageVirtualMachine,
    Volume,
    VolumeOntapConfiguration,
    VolumeOpenZFSConfiguration,
)
from utils import (
    InstanceTypesData,
    create_s3_bucket,
    delete_s3_bucket,
    dict_add_nested_key,
    dict_has_nested_key,
    generate_stack_name,
    get_architecture_supported_by_instance_type,
    get_arn_partition,
    get_instance_info,
    get_metadata,
    get_network_interfaces_count,
    get_vpc_snakecase_value,
    random_alphanumeric,
    to_pascal_case,
)
from xdist import get_xdist_worker_id

from tests.common.osu_common import PRIVATE_OSES, run_osu_benchmarks
from tests.common.schedulers_common import get_scheduler_commands
from tests.common.storage.constants import StorageType
from tests.common.storage.ebs_utils import delete_ebs_volume
from tests.common.storage.efs_utils import delete_efs_filesystem
from tests.common.storage.fsx_utils import delete_fsx_filesystem
from tests.common.utils import (
    fetch_instance_slots,
    get_installed_parallelcluster_version,
    retrieve_latest_ami,
    retrieve_pcluster_ami_without_standard_naming,
)
from tests.storage.snapshots_factory import EBSSnapshotsFactory

pytest_plugins = ["conftest_networking", "conftest_resource_bucket", "conftest_runtest_hooks"]


def pytest_addoption(parser):
    """Register argparse-style options and ini-style config values, called once at the beginning of a test run."""
    parser.addoption("--tests-config-file", help="config file to specify tests and dimensions")
    parser.addoption("--regions", help="aws region where tests are executed", nargs="*")
    parser.addoption("--instances", help="aws instances under test", nargs="*")
    parser.addoption("--oss", help="OSs under test", nargs="*")
    parser.addoption("--schedulers", help="schedulers under test", nargs="*")
    parser.addoption("--tests-log-file", help="file used to write test logs", default="pytest.log")
    parser.addoption("--output-dir", help="output dir for tests artifacts")
    # Can't mark fields as required due to: https://github.com/pytest-dev/pytest/issues/2026
    parser.addoption("--key-name", help="key to use for EC2 instances", type=str)
    parser.addoption("--key-path", help="key path to use for SSH connections", type=str)
    parser.addoption("--custom-chef-cookbook", help="url to a custom cookbook package")
    parser.addoption(
        "--createami-custom-chef-cookbook", help="url to a custom cookbook package for the build-image command"
    )
    parser.addoption("--pcluster-git-ref", help="Git ref of the custom cli package used to build the AMI.")
    parser.addoption("--cookbook-git-ref", help="Git ref of the custom cookbook package used to build the AMI.")
    parser.addoption("--node-git-ref", help="Git ref of the custom node package used to build the AMI.")
    parser.addoption(
        "--ami-owner",
        help="Override the owner value when fetching AMIs to use with cluster. By default pcluster uses amazon.",
    )
    parser.addoption(
        "--available-amis-oss-x86",
        help="(optional) set to available x86 AMIs OSes in the account. "
        "If not specified, all supported OSes will be used.",
    )
    parser.addoption(
        "--available-amis-oss-arm",
        help="(optional) set to available ARM AMIs OSes in the account. "
        "If not specified, all supported OSes will be used.",
    )
    parser.addoption("--createami-custom-node-package", help="url to a custom node package for the build-image command")
    parser.addoption("--custom-awsbatch-template-url", help="url to a custom awsbatch template")
    parser.addoption("--cw-dashboard-template-url", help="url to a custom Dashboard cfn template")
    parser.addoption("--custom-awsbatchcli-package", help="url to a custom awsbatch cli package")
    parser.addoption("--custom-node-package", help="url to a custom node package")
    parser.addoption("--custom-ami", help="custom AMI to use in the tests")
    parser.addoption("--pre-install", help="url to pre install script")
    parser.addoption("--post-install", help="url to post install script")
    parser.addoption("--vpc-stack", help="Name of an existing vpc stack.")
    parser.addoption("--cluster", help="Use an existing cluster instead of creating one.")
    parser.addoption("--policies-uri", help="Use an existing policies URI instead of uploading one.")
    parser.addoption(
        "--cluster-custom-resource-service-token",
        help="(Optional) ServiceToken (ARN) of the CloudFormation Cluster custom resource provider.",
    )
    parser.addoption(
        "--resource-bucket",
        help="(Optional) Name of bucket to use to look for standard resources like hosted CloudFormation templates.",
    )
    parser.addoption("--lambda-layer-source", help="(Optional) S3 URI of lambda layer to copy rather than building.")
    parser.addoption("--api-definition-s3-uri", help="URI of the OpenAPI spec of the ParallelCluster API")
    parser.addoption(
        "--api-infrastructure-s3-uri", help="URI of the CloudFormation template for the ParallelCluster API"
    )
    parser.addoption("--api-uri", help="URI of an existing ParallelCluster API")
    parser.addoption("--instance-types-data-file", help="JSON file with additional instance types data")
    parser.addoption(
        "--credential", help="STS credential endpoint, in the format <region>,<endpoint>,<ARN>,<externalId>.", nargs="+"
    )
    parser.addoption(
        "--no-delete", action="store_true", default=False, help="Don't delete stacks after tests are complete."
    )
    parser.addoption(
        "--retain-ad-stack", action="store_true", default=False, help="Retain AD stack and corresponding VPC stack."
    )
    parser.addoption("--benchmarks", action="store_true", default=False, help="enable benchmark tests")
    parser.addoption("--scaling-test-config", help="Path to scaling test config file")
    parser.addoption("--stackname-suffix", help="set a suffix in the integration tests stack names")
    parser.addoption(
        "--delete-logs-on-success", help="delete CloudWatch logs when a test succeeds", action="store_true"
    )
    parser.addoption(
        "--use-default-iam-credentials",
        help="use default IAM creds when running pcluster commands",
        action="store_true",
    )
    parser.addoption("--iam-user-role-stack-name", help="Name of CFN stack providing IAM user roles.")
    parser.addoption(
        "--directory-stack-name",
        help="Name of CFN stack providing AD domain to be used for testing AD integration feature.",
    )
    parser.addoption(
        "--ldaps-nlb-stack-name",
        help="Name of CFN stack providing NLB to enable use of LDAPS with a Simple AD directory when testing AD "
        "integration feature.",
    )
    parser.addoption(
        "--slurm-database-stack-name",
        help="Name of CFN stack providing database stack to be used for testing Slurm accounting feature.",
    )
    parser.addoption(
        "--slurm-dbd-stack-name",
        help="Name of CFN stack providing external Slurm dbd stack to be used for testing Slurm accounting feature.",
    )
    parser.addoption(
        "--munge-key-secret-arn",
        help="ARN of the secret containing the munge key to be used for testing Slurm accounting feature.",
    )
    parser.addoption("--external-shared-storage-stack-name", help="Name of existing external shared storage stack.")
    parser.addoption("--bucket-name", help="Name of existing bucket.")
    parser.addoption("--custom-security-groups-stack-name", help="Name of existing custom security groups stack.")
    parser.addoption(
        "--force-run-instances",
        help="Force the usage of EC2 run-instances boto3 API instead of create-fleet for compute fleet scaling up."
        " Note: If there are multiple instances in the list, only the first will be used.",
        action="store_true",
    )
    parser.addoption(
        "--force-elastic-ip",
        help="Force the usage of Elastic IP for Multi network interface EC2 instances.",
        action="store_true",
    )
    parser.addoption(
        "--global-build-number",
        help="The build number passed from the testing pipelines",
        default=0,
    )
    parser.addoption(
        "--proxy-stack",
        help="Name of CFN stack providing a Proxy environment.",
    )
    parser.addoption(
        "--build-image-roles-stack",
        help="Name of CFN stack providing the build image permissions.",
    )
    parser.addoption(
        "--api-stack",
        help="Name of CFN stack providing the ParallelCluster API infrastructure.",
    )


def pytest_generate_tests(metafunc):
    """Generate (multiple) parametrized calls to a test function."""
    if metafunc.config.getoption("tests_config", None):
        parametrize_from_config(metafunc)
    else:
        _parametrize_from_option(metafunc, "region", "regions")
        _parametrize_from_option(metafunc, "instance", "instances")
        _parametrize_from_option(metafunc, "os", "oss")
        _parametrize_from_option(metafunc, "scheduler", "schedulers")


def pytest_configure(config):
    """This hook is called for every plugin and initial conftest file after command line options have been parsed."""
    # read tests config file if used
    if config.getoption("tests_config_file", None):
        config.option.tests_config = read_config_file(config.getoption("tests_config_file"), config=config)

    # Read instance types data file if used
    if config.getoption("instance_types_data_file", None):
        # Load additional instance types data
        InstanceTypesData.load_additional_instance_types_data(config.getoption("instance_types_data_file"))
        config.option.instance_types_data = InstanceTypesData.additional_instance_types_data

    # register additional markers
    config.addinivalue_line("markers", "instances(instances_list): run test only against the listed instances.")
    config.addinivalue_line("markers", "regions(regions_list): run test only against the listed regions")
    config.addinivalue_line("markers", "oss(os_list): run test only against the listed oss")
    config.addinivalue_line("markers", "schedulers(schedulers_list): run test only against the listed schedulers")
    config.addinivalue_line(
        "markers", "dimensions(region, instance, os, scheduler): run test only against the listed dimensions"
    )
    config.addinivalue_line("markers", "skip_instances(instances_list): skip test for the listed instances")
    config.addinivalue_line("markers", "skip_regions(regions_list): skip test for the listed regions")
    config.addinivalue_line("markers", "skip_oss(os_list): skip test for the listed oss")
    config.addinivalue_line("markers", "skip_schedulers(schedulers_list): skip test for the listed schedulers")
    config.addinivalue_line(
        "markers", "skip_dimensions(region, instance, os, scheduler): skip test for the listed dimensions"
    )

    _setup_custom_logger(config.getoption("tests_log_file"))


def pytest_sessionstart(session: pytest.Session):
    # The number of seconds before a connection to the instance metadata service should time out.
    # When attempting to retrieve credentials on an Amazon EC2 instance that is configured with an IAM role,
    # a connection to the instance metadata service will time out after 1 second by default. If you know you're
    # running on an EC2 instance with an IAM role configured, you can increase this value if needed.
    os.environ["AWS_METADATA_SERVICE_TIMEOUT"] = "5"
    # When attempting to retrieve credentials on an Amazon EC2 instance that has been configured with an IAM role,
    # Boto3 will make only one attempt to retrieve credentials from the instance metadata service before giving up.
    # If you know your code will be running on an EC2 instance, you can increase this value to make Boto3 retry
    # multiple times before giving up.
    os.environ["AWS_METADATA_SERVICE_NUM_ATTEMPTS"] = "5"
    # Increasing default max attempts retry
    os.environ["AWS_MAX_ATTEMPTS"] = "10"


def pytest_fixture_setup(fixturedef: FixtureDef[Any], request: SubRequest) -> Optional[object]:
    logging.info("Setting up fixture %s", fixturedef)
    return None


def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: List[pytest.Item]):
    """Called after collection has been performed, may filter or re-order the items in-place."""
    if config.getoption("tests_config", None):
        # Remove tests not declared in config file from the collected ones
        remove_disabled_tests(session, config, items)
        # Apply filtering based on dimensions passed as CLI options
        # ("--regions", "--instances", "--oss", "--schedulers")
        apply_cli_dimensions_filtering(config, items)
    else:
        add_default_markers(items)
        check_marker_list(items, "instances", "instance")
        check_marker_list(items, "regions", "region")
        check_marker_list(items, "oss", "os")
        check_marker_list(items, "schedulers", "scheduler")
        check_marker_skip_list(items, "skip_instances", "instance")
        check_marker_skip_list(items, "skip_regions", "region")
        check_marker_skip_list(items, "skip_oss", "os")
        check_marker_skip_list(items, "skip_schedulers", "scheduler")
        check_marker_dimensions(items)
        check_marker_skip_dimensions(items)

    add_filename_markers(items, config)


def pytest_collection_finish(session):
    _log_collected_tests(session)
    # Create the metadata table after the regions are collected
    try:
        region = session.config.getoption("regions") or get_all_regions(session.config.getoption("tests_config"))
        region = [unmarshal_az_override(az) for az in region]
        # Use the first element of the list of regions, since there must be at least one
        reporting_region = get_reporting_region(region[0])
        logging.info(f"Metadata reporting region {reporting_region}")
        # Setup the metadata table in case it doesn't exist
        MetadataTableManager(reporting_region, METADATA_TABLE).create_metadata_table()
    except Exception as exc:
        logging.info(f"There was a '{type(exc)}' error with '{exc}' when creating the table!")


def _log_collected_tests(session):
    from xdist import get_xdist_worker_id

    # Write collected tests in a single worker
    # get_xdist_worker_id returns the id of the current worker ('gw0', 'gw1', etc) or 'master'
    if get_xdist_worker_id(session) in ["master", "gw0"]:
        collected_tests = list(map(lambda item: item.nodeid, session.items))
        region = session.config.getoption("regions") or get_all_regions(session.config.getoption("tests_config"))
        region = [unmarshal_az_override(az) for az in region]
        logging.info(
            "Collected tests in regions %s (total=%d):\n%s",
            region,
            len(session.items),
            json.dumps(collected_tests, indent=2),
        )
        out_dir = session.config.getoption("output_dir")
        with open(f"{out_dir}/collected_tests.txt", "a", encoding="utf-8") as out_f:
            out_f.write("\n".join(collected_tests))
            out_f.write("\n")


def pytest_exception_interact(
    node: Union[pytest.Item, pytest.Collector],
    call: pytest.CallInfo,
    report: Union[pytest.CollectReport, pytest.TestReport],
):
    """Called when an exception was raised which can potentially be interactively handled.."""
    logging.error(
        "Exception raised while executing %s: %s\n%s",
        node.name,
        call.excinfo.value,
        "".join(format_tb(call.excinfo.tb)),
    )


def _parametrize_from_option(metafunc, test_arg_name, option_name):
    if test_arg_name in metafunc.fixturenames:
        metafunc.parametrize(test_arg_name, metafunc.config.getoption(option_name), scope="class")


def _setup_custom_logger(log_file):
    formatter = logging.Formatter(fmt="%(asctime)s - %(levelname)s - %(process)d - %(module)s - %(message)s")
    logger = logging.getLogger()
    logger.handlers = []

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


@pytest.fixture(scope="class")
@pytest.mark.usefixtures("setup_credentials")
def clusters_factory(request, region):
    """
    Define a fixture to manage the creation and destruction of clusters.

    The configs used to create clusters are dumped to output_dir/clusters_configs/{test_name}.config
    """
    factory = ClustersFactory(delete_logs_on_success=request.config.getoption("delete_logs_on_success"))

    def _cluster_factory(cluster_config, upper_case_cluster_name=False, custom_cli_credentials=None, **kwargs):
        cluster_config = _write_config_to_outdir(request, cluster_config, "clusters_configs")
        cluster_name = (
            request.config.getoption("cluster")
            if request.config.getoption("cluster")
            else "integ-tests-{0}{1}{2}".format(
                random_alphanumeric().upper() if upper_case_cluster_name else random_alphanumeric(),
                "-" if request.config.getoption("stackname_suffix") else "",
                request.config.getoption("stackname_suffix"),
            )
        )
        request.node.user_properties.append(("cluster_stack_name", f"{cluster_name}"))
        request.node.user_properties.append(("cw_log_group_name", f"{cluster_name}"))
        cluster = Cluster(
            name=cluster_name,
            config_file=cluster_config,
            ssh_key=request.config.getoption("key_path"),
            region=region,
            custom_cli_credentials=custom_cli_credentials,
        )
        if not request.config.getoption("cluster"):
            cluster.creation_response = factory.create_cluster(cluster, **kwargs)
        return cluster

    yield _cluster_factory
    if not request.config.getoption("no_delete"):
        try:
            test_passed = request.node.rep_call.passed
        except AttributeError:
            test_passed = False
        factory.destroy_all_clusters(test_passed=test_passed)


@pytest.fixture(scope="class")
def api_server_factory(
    cfn_stacks_factory, request, resource_bucket, policies_uri, api_definition_s3_uri, api_infrastructure_s3_uri
):
    """Creates a factory for deploying API servers on-demand to each region."""
    api_servers = {}

    def _api_server_factory(server_region):
        option = "api_stack"
        if request.config.getoption(option):
            api_stack_name = request.config.getoption(option)
            logging.info(f"Using existing ParallelCluster API stack in {server_region}: {api_stack_name}")
            api_servers[server_region] = CfnStack(name=api_stack_name, region=server_region, template=None)
        else:
            api_stack_name = generate_stack_name("integ-tests-api", request.config.getoption("stackname_suffix"))

            params = [
                {"ParameterKey": "EnableIamAdminAccess", "ParameterValue": "true"},
                {"ParameterKey": "CreateApiUserRole", "ParameterValue": "false"},
            ]
            if api_definition_s3_uri:
                params.append({"ParameterKey": "ApiDefinitionS3Uri", "ParameterValue": api_definition_s3_uri})
            if policies_uri:
                params.append({"ParameterKey": "PoliciesTemplateUri", "ParameterValue": policies_uri})
            if resource_bucket:
                params.append({"ParameterKey": "CustomBucket", "ParameterValue": resource_bucket})

            template = (
                api_infrastructure_s3_uri
                or f"https://{resource_bucket}.s3.{server_region}.amazonaws.com"
                f"{'.cn' if server_region.startswith('cn') else ''}"
                f"/parallelcluster/{get_installed_parallelcluster_version()}/api/parallelcluster-api.yaml"
            )
            if server_region not in api_servers:
                logging.info(f"Creating API Server stack: {api_stack_name} in {server_region} with template {template}")
                stack = CfnStack(
                    name=api_stack_name,
                    region=server_region,
                    parameters=params,
                    capabilities=["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
                    template=template,
                )
                cfn_stacks_factory.create_stack(stack)
                api_servers[server_region] = stack
                time.sleep(15)
            else:
                logging.info(f"Found cached API Server stack: {api_stack_name} in {server_region}")

        return api_servers[server_region]

    yield _api_server_factory


@pytest.fixture(scope="class")
def api_client(region, api_server_factory, api_uri):
    """Define a fixture for an API client that interacts with the pcluster api."""
    from pcluster_client import ApiClient, Configuration

    if api_uri:
        host = api_uri
    else:
        stack = api_server_factory(region)
        host = stack.cfn_outputs["ParallelClusterApiInvokeUrl"]

    api_configuration = Configuration(host=host)
    api_configuration.retries = 3

    with ApiClient(api_configuration) as api_client_instance:
        yield api_client_instance


@pytest.fixture(scope="class")
@pytest.mark.usefixtures("setup_credentials")
def images_factory(request):
    """
    Define a fixture to manage the creation and destruction of images.

    The configs used to create clusters are dumped to output_dir/images_configs/{test_name}.config
    """
    factory = ImagesFactory()

    def _image_factory(image_id, image_config, region, **kwargs):
        image_config_file = _write_config_to_outdir(request, image_config, "image_configs")
        image = Image(
            image_id=(
                "-".join([image_id, request.config.getoption("stackname_suffix")])
                if request.config.getoption("stackname_suffix")
                else image_id
            ),
            config_file=image_config_file,
            region=region,
        )
        factory.create_image(image, **kwargs)
        if image.image_status != "BUILD_IN_PROGRESS" and kwargs.get("log_error", False):
            logging.error("image %s creation failed", image_id)

        return image

    yield _image_factory

    if not request.config.getoption("no_delete"):
        factory.destroy_all_images()
    else:
        logging.warning("Skipping deletion of CFN image stacks because --no-delete option is set")


def _write_config_to_outdir(request, config, config_dir):
    out_dir = request.config.getoption("output_dir")

    # Sanitize config file name to make it Windows compatible
    # request.node.nodeid example:
    # 'dcv/test_dcv.py::test_dcv_configuration[eu-west-1-c5.xlarge-centos7-slurm-8443-0.0.0.0/0-/shared]'
    test_file, test_name = request.node.nodeid.split("::", 1)
    config_file_name = "{0}-{1}".format(test_file, test_name.replace("/", "_"))

    os.makedirs(
        "{out_dir}/{config_dir}/{test_dir}".format(
            out_dir=out_dir, config_dir=config_dir, test_dir=os.path.dirname(test_file)
        ),
        exist_ok=True,
    )
    config_dst = "{out_dir}/{config_dir}/{config_file_name}.config".format(
        out_dir=out_dir, config_dir=config_dir, config_file_name=config_file_name
    )
    copyfile(config, config_dst)
    return config_dst


@pytest.fixture()
def test_datadir(request, datadir):
    """
    Inject the datadir with resources for the specific test function.

    If the test function is declared in a class then datadir is ClassName/FunctionName
    otherwise it is only FunctionName.
    """
    function_name = request.function.__name__
    if not request.cls:
        return datadir / function_name

    class_name = request.cls.__name__
    return datadir / "{0}/{1}".format(class_name, function_name)


@pytest.fixture()
def pcluster_config_reader(test_datadir, vpc_stack, request, region, architecture):
    """
    Define a fixture to render pcluster config templates associated to the running test.

    The config for a given test is a pcluster.config.yaml file stored in the configs_datadir folder.
    The config can be written by using Jinja2 template engine.
    The current renderer already replaces placeholders for current keys:
        {{ region }}, {{ os }}, {{ instance }}, {{ scheduler}}, {{ key_name }},
        {{ vpc_id }}, {{ public_subnet_id }}, {{ private_subnet_id }}, {{ default_vpc_security_group_id }}
    The current renderer injects options for custom templates and packages in case these
    are passed to the cli and not present already in the cluster config.
    Also sanity_check is set to true by default unless explicitly set in config.

    :return: a _config_renderer(**kwargs) function which gets as input a dictionary of values to replace in the template
    """

    def _config_renderer(config_file="pcluster.config.yaml", benchmarks=None, output_file=None, **kwargs):
        config_file_path = test_datadir / config_file
        if not os.path.isfile(config_file_path):
            raise FileNotFoundError(f"Cluster config file not found in the expected dir {config_file_path}")
        output_file_path = test_datadir / output_file if output_file else config_file_path
        default_values = _get_default_template_values(vpc_stack, request)
        kwargs = inject_internal_storage_settings(**kwargs)
        file_loader = FileSystemLoader(str(test_datadir))
        env = SandboxedEnvironment(loader=file_loader)
        rendered_template = env.get_template(config_file).render(**{**default_values, **kwargs})
        output_file_path.write_text(rendered_template)
        if not config_file.endswith("image.config.yaml"):
            inject_additional_config_settings(output_file_path, request, region, architecture, benchmarks)
        else:
            inject_additional_image_configs_settings(output_file_path, request)
        return output_file_path

    return _config_renderer


def inject_internal_storage_settings(**kwargs):
    if not kwargs.get("shared_headnode_storage_type"):
        kwargs["shared_headnode_storage_type"] = "Efs"
    return kwargs


def inject_additional_image_configs_settings(image_config, request):
    with open(image_config, encoding="utf-8") as conf_file:
        config_content = yaml.load(conf_file, Loader=yaml.SafeLoader)

    if request.config.getoption("createami_custom_chef_cookbook") and not dict_has_nested_key(
        config_content, ("DevSettings", "Cookbook", "ChefCookbook")
    ):
        dict_add_nested_key(
            config_content,
            request.config.getoption("createami_custom_chef_cookbook"),
            ("DevSettings", "Cookbook", "ChefCookbook"),
        )

    for option, config_param in [
        ("custom_awsbatchcli_package", "AwsBatchCliPackage"),
        ("createami_custom_node_package", "NodePackage"),
    ]:
        if request.config.getoption(option) and not dict_has_nested_key(config_content, ("DevSettings", config_param)):
            dict_add_nested_key(config_content, request.config.getoption(option), ("DevSettings", config_param))

    with open(image_config, "w", encoding="utf-8") as conf_file:
        yaml.dump(config_content, conf_file)


def _inject_additional_iam_policies(node_config, additional_iam_policies):
    if dict_has_nested_key(node_config, ("Iam", "AdditionalIamPolicies")):
        for policy in additional_iam_policies:
            if policy not in node_config["Iam"]["AdditionalIamPolicies"]:
                node_config["Iam"]["AdditionalIamPolicies"] += [copy.deepcopy(policy)]
    else:
        # InstanceProfile, InstanceRole or AdditionalIamPolicies can not be configured together.
        if not (
            dict_has_nested_key(node_config, ("Iam", "InstanceRole"))
            or dict_has_nested_key(node_config, ("Iam", "InstanceProfile"))
        ):
            dict_add_nested_key(node_config, additional_iam_policies, ("Iam", "AdditionalIamPolicies"))


def _inject_additional_iam_policies_for_nodes(
    config_content, scheduler: str, node_types: List[NodeType], policies: List[Dict]
):
    if NodeType.HEAD_NODE in node_types:
        _inject_additional_iam_policies(config_content["HeadNode"], policies)
    if (
        scheduler == "slurm"
        and dict_has_nested_key(config_content, ("Scheduling", "SlurmQueues"))
        and NodeType.COMPUTE_NODES in node_types
    ):
        for queue in config_content["Scheduling"]["SlurmQueues"]:
            _inject_additional_iam_policies(queue, policies)
    if (
        scheduler == "slurm"
        and dict_has_nested_key(config_content, ("LoginNodes", "Pools"))
        and NodeType.LOGIN_NODES in node_types
    ):
        for pool in config_content["LoginNodes"]["Pools"]:
            _inject_additional_iam_policies(pool, policies)


def inject_additional_config_settings(cluster_config, request, region, architecture, benchmarks=None):  # noqa C901
    with open(cluster_config, encoding="utf-8") as conf_file:
        config_content = yaml.safe_load(conf_file)

    if not dict_has_nested_key(config_content, ("HeadNode", "Ssh", "AllowedIps")):
        # If the test is running in an EC2 instance limit SSH connection access from instance running the test
        instance_ip = get_metadata("public-ipv4", raise_error=False)
        if not instance_ip:
            instance_ip = get_metadata("local-ipv4", raise_error=False)
        if instance_ip:
            logging.info(f"Limiting AllowedIps rule to IP: {instance_ip}")
            dict_add_nested_key(config_content, f"{instance_ip}/32", ("HeadNode", "Ssh", "AllowedIps"))
        else:
            logging.info("Skipping AllowedIps rule because unable to find local and public IP for the instance.")

    if request.config.getoption("custom_chef_cookbook") and not dict_has_nested_key(
        config_content, ("DevSettings", "Cookbook", "ChefCookbook")
    ):
        dict_add_nested_key(
            config_content,
            request.config.getoption("custom_chef_cookbook"),
            ("DevSettings", "Cookbook", "ChefCookbook"),
        )

    if request.config.getoption("custom_ami") and not dict_has_nested_key(config_content, ("Image", "CustomAmi")):
        dict_add_nested_key(config_content, request.config.getoption("custom_ami"), ("Image", "CustomAmi"))
    # Adding Internal AMI we create for integration testing of those OSses which we do not publicly publish/release
    if config_content["Image"]["Os"] in PRIVATE_OSES and not dict_has_nested_key(
        config_content, ("Image", "CustomAmi")
    ):
        dict_add_nested_key(
            config_content,
            retrieve_latest_ami(
                region,
                config_content["Image"]["Os"],
                ami_type="pcluster",
                architecture=architecture,
            ),
            ("Image", "CustomAmi"),
        )

    if not dict_has_nested_key(config_content, ("DevSettings", "AmiSearchFilters")):
        if (
            request.config.getoption("pcluster_git_ref")
            or request.config.getoption("cookbook_git_ref")
            or request.config.getoption("node_git_ref")
        ):
            tags = []
            if request.config.getoption("pcluster_git_ref"):
                tags.append(
                    {"Key": "build:parallelcluster:cli_ref", "Value": request.config.getoption("pcluster_git_ref")}
                )
            if request.config.getoption("cookbook_git_ref"):
                tags.append(
                    {"Key": "build:parallelcluster:cookbook_ref", "Value": request.config.getoption("cookbook_git_ref")}
                )
            if request.config.getoption("node_git_ref"):
                tags.append(
                    {"Key": "build:parallelcluster:node_ref", "Value": request.config.getoption("node_git_ref")}
                )
            tags.append({"Key": "parallelcluster:build_status", "Value": "available"})
            dict_add_nested_key(config_content, tags, ("DevSettings", "AmiSearchFilters", "Tags"))
        if request.config.getoption("ami_owner"):
            dict_add_nested_key(
                config_content, request.config.getoption("ami_owner"), ("DevSettings", "AmiSearchFilters", "Owner")
            )

    # Additional instance types data is copied it into config files to make it available at cluster creation
    instance_types_data = request.config.getoption("instance_types_data", None)
    if instance_types_data:
        dict_add_nested_key(config_content, json.dumps(instance_types_data), ("DevSettings", "InstanceTypesData"))

    scheduler = config_content["Scheduling"]["Scheduler"]
    for option, config_param in [("pre_install", "OnNodeStart"), ("post_install", "OnNodeConfigured")]:
        if request.config.getoption(option):
            if not dict_has_nested_key(config_content, ("HeadNode", "CustomActions", config_param)):
                dict_add_nested_key(
                    config_content,
                    request.config.getoption(option),
                    ("HeadNode", "CustomActions", config_param, "Script"),
                )
                _add_policy_for_pre_post_install(config_content["HeadNode"], option, request, region)

            if scheduler != "awsbatch":
                scheduler_prefix = scheduler.capitalize()
                for queue in config_content["Scheduling"][f"{scheduler_prefix}Queues"]:
                    if not dict_has_nested_key(queue, ("CustomActions", config_param)):
                        dict_add_nested_key(
                            queue, request.config.getoption(option), ("CustomActions", config_param, "Script")
                        )
                        _add_policy_for_pre_post_install(queue, option, request, region)

    for option, config_param in [
        ("custom_awsbatchcli_package", "AwsBatchCliPackage"),
        ("custom_node_package", "NodePackage"),
    ]:
        if request.config.getoption(option) and not dict_has_nested_key(config_content, ("DevSettings", config_param)):
            dict_add_nested_key(config_content, request.config.getoption(option), ("DevSettings", config_param))

    if request.config.getoption("benchmarks") and benchmarks and scheduler == "slurm":
        # If benchmarks are enabled and there are benchmarks to run for the test,
        # placement groups are added to queue to ensure the performance is comparable with previous runs.
        for queue in config_content["Scheduling"]["SlurmQueues"]:
            networking = queue["Networking"]
            if not networking.get("PlacementGroup"):
                networking["PlacementGroup"] = {"Enabled": True}
            for compute_resource in queue["ComputeResources"]:
                if not compute_resource.get("MaxCount"):
                    # Use larger max count to support performance tests if not specified explicitly.
                    compute_resource["MaxCount"] = 150

    # Forcing the usage of Run-instance API for creation of fleet
    # when we use InstanceType instead of Instances/InstanceType
    if (
        scheduler == "slurm"
        and dict_has_nested_key(config_content, ("Scheduling", "SlurmQueues"))
        and request.config.getoption("force_run_instances")
    ):
        for queues in config_content["Scheduling"]["SlurmQueues"]:
            if dict_has_nested_key(queues, ["ComputeResources"]):
                for compute_resources in queues["ComputeResources"]:
                    if dict_has_nested_key(compute_resources, ["Instances"]):
                        instance_type = compute_resources["Instances"][0]["InstanceType"]
                        compute_resources.pop("Instances")
                        compute_resources["InstanceType"] = instance_type

    # Force addition of ElasticIp as True for Multi Nic instance
    if request.config.getoption("force_elastic_ip"):
        if not dict_has_nested_key(config_content, ("HeadNode", "Networking", "ElasticIp")):
            dict_add_nested_key(config_content, "true", ("HeadNode", "Networking", "ElasticIp"))
        elif dict_has_nested_key(config_content, ("HeadNode", "Networking", "ElasticIp")):
            dict_add_nested_key(config_content, "true", ("HeadNode", "Networking", "ElasticIp"))

    additional_policies = [
        {"Policy": f"arn:{get_arn_partition(region)}:iam::aws:policy/AmazonSSMManagedInstanceCore"},
    ]
    _inject_additional_iam_policies_for_nodes(
        config_content,
        scheduler,
        node_types=[NodeType.LOGIN_NODES, NodeType.HEAD_NODE, NodeType.COMPUTE_NODES],
        policies=additional_policies,
    )

    with open(cluster_config, "w", encoding="utf-8") as conf_file:
        yaml.dump(config_content, conf_file)


def _add_policy_for_pre_post_install(node_config, custom_option, request, region):
    match = re.match(r"s3://(.*?)/(.*)", request.config.getoption(custom_option))
    if not match or len(match.groups()) < 2:
        logging.info("{0} script is not an S3 URL".format(custom_option))
    else:
        additional_iam_policies = [
            {"Policy": f"arn:{get_arn_partition(region)}:iam::aws:policy/AmazonS3ReadOnlyAccess"}
        ]
        if dict_has_nested_key(node_config, ("Iam", "InstanceRole")) or dict_has_nested_key(
            node_config, ("Iam", "InstanceProfile")
        ):
            # AdditionalIamPolicies, InstanceRole or InstanceProfile can not co-exist
            logging.info(
                "InstanceRole/InstanceProfile is specified, "
                f"skipping insertion of AdditionalIamPolicies: {additional_iam_policies}"
            )
        else:
            logging.info(
                f"{custom_option} script is an S3 URL, adding AdditionalIamPolicies: {additional_iam_policies}"
            )
            _inject_additional_iam_policies(node_config, additional_iam_policies)


def _get_default_template_values(vpc_stack: CfnVpcStack, request):
    """Build a dictionary of default values to inject in the jinja templated cluster configs."""
    default_values = get_vpc_snakecase_value(vpc_stack)
    default_values["public_subnet_id"] = vpc_stack.get_public_subnet()
    default_values["public_subnet_ids"] = vpc_stack.get_all_public_subnets()
    default_values["private_subnet_id"] = vpc_stack.get_private_subnet()
    default_values["private_subnet_ids"] = vpc_stack.get_all_private_subnets()
    default_values.update({dimension: request.node.funcargs.get(dimension) for dimension in DIMENSIONS_MARKER_ARGS})
    default_values["partition"] = get_arn_partition(default_values["region"])
    default_values["key_name"] = request.config.getoption("key_name")

    default_values["imds_secured"] = default_values.get("scheduler") in SCHEDULERS_SUPPORTING_IMDS_SECURED
    default_values["scheduler_prefix"] = {"slurm": "Slurm", "awsbatch": "AwsBatch"}.get(default_values.get("scheduler"))
    return default_values


@pytest.fixture(scope="session")
def cfn_stacks_factory(request):
    """Define a fixture to manage the creation and destruction of CloudFormation stacks."""
    factory = CfnStacksFactory(request.config.getoption("credential"))
    yield factory
    if not request.config.getoption("no_delete"):
        excluded_stacks = []
        if request.config.getoption("retain_ad_stack"):
            excluded_stacks.extend(["vpc", "SimpleAD", "MicrosoftAD"])
            logging.warning("Skipping deletion of AD and VPC stacks because --retain-ad-stack option is set")
        factory.delete_all_stacks(excluded_stacks)
    else:
        logging.warning("Skipping deletion of CFN stacks because --no-delete option is set")


@pytest.fixture()
@pytest.mark.usefixtures("setup_credentials")
def parameterized_cfn_stacks_factory(request):
    """Define a fixture that returns a parameterized stack factory and manages the stack creation and deletion."""
    factory = CfnStacksFactory(request.config.getoption("credential"))

    def _create_stack(
        region, template_path, stack_prefix="", parameters=None, capabilities=None, stack_is_under_test=False
    ):
        file_content = extract_template(template_path)
        stack = CfnStack(
            name=generate_stack_name(stack_prefix, request.config.getoption("stackname_suffix")),
            region=region,
            template=file_content,
            parameters=parameters or [],
            capabilities=capabilities or [],
        )
        factory.create_stack(stack, stack_is_under_test=stack_is_under_test)
        return stack

    def extract_template(template_path):
        with open(template_path, encoding="utf-8") as cfn_file:
            file_content = cfn_file.read()
        return file_content

    yield _create_stack
    factory.delete_all_stacks()


@pytest.fixture(scope="class", autouse=True)
def setup_credentials(region, request):
    """Setup environment for the integ tests"""
    with aws_credential_provider(region, request.config.getoption("credential")):
        yield


# FixMe: double check if this fixture introduce unnecessary implication.
#  The alternative way is to use --region for all cluster operations.
@pytest.fixture(scope="class", autouse=True)
def setup_env_variable(region):
    """Setup environment for the integ tests"""
    os.environ["AWS_DEFAULT_REGION"] = region
    yield
    del os.environ["AWS_DEFAULT_REGION"]


@xdist_session_fixture(autouse=True)
def initialize_cli_creds(request):
    if request.config.getoption("use_default_iam_credentials"):
        logging.info("Using default IAM credentials to run pcluster commands")
        yield None
    else:
        stack_factory = CfnStacksFactory(request.config.getoption("credential"))

        regions = request.config.getoption("regions") or get_all_regions(request.config.getoption("tests_config"))
        stack_template_path = os.path.join("..", "iam_policies", "user-role.cfn.yaml")
        with open(stack_template_path, encoding="utf-8") as stack_template_file:
            stack_template_data = stack_template_file.read()
        cli_creds = {}
        for region in regions:
            # region may contain an az_id if an override was specified
            # here we ensure that we are using the region
            region = unmarshal_az_override(region)
            if request.config.getoption("iam_user_role_stack_name"):
                stack_name = request.config.getoption("iam_user_role_stack_name")
                logging.info(f"Using stack {stack_name} in region {region}")
                stack = CfnStack(
                    name=stack_name, region=region, capabilities=["CAPABILITY_IAM"], template=stack_template_data
                )
            else:
                logging.info("Creating IAM roles for pcluster CLI")
                stack_name = generate_stack_name(
                    "integ-tests-iam-user-role", request.config.getoption("stackname_suffix")
                )
                stack = CfnStack(
                    name=stack_name, region=region, capabilities=["CAPABILITY_IAM"], template=stack_template_data
                )

                stack_factory.create_stack(stack)
            cli_creds[region] = stack.cfn_outputs["ParallelClusterUserRole"]

        yield cli_creds

        if not request.config.getoption("no_delete"):
            stack_factory.delete_all_stacks()
        else:
            logging.warning("Skipping deletion of CFN stacks because --no-delete option is set")


@pytest.fixture(scope="session", autouse=True)
def register_cli_credentials(initialize_cli_creds):
    if initialize_cli_creds:
        for region, creds in initialize_cli_creds.items():
            register_cli_credentials_for_region(region, creds)


@pytest.fixture(scope="class")
@pytest.mark.usefixtures("clusters_factory", "images_factory")
def create_roles_stack(request, region):
    """Define a fixture that returns a stack factory for IAM roles."""
    logging.info("Creating IAM roles stack")
    factory = CfnStacksFactory(request.config.getoption("credential"))

    def _create_stack(stack_prefix, roles_file):
        stack_template_path = os.path.join("..", "iam_policies", roles_file)
        template_data = read_template(stack_template_path)
        stack = CfnStack(
            name=generate_stack_name(stack_prefix, request.config.getoption("stackname_suffix")),
            region=region,
            template=template_data,
            capabilities=["CAPABILITY_IAM"],
        )
        factory.create_stack(stack)
        return stack

    def read_template(template_path):
        with open(template_path, encoding="utf-8") as cfn_file:
            file_content = cfn_file.read()
        return file_content

    yield _create_stack
    if not request.config.getoption("no_delete"):
        factory.delete_all_stacks()
    else:
        logging.warning("Skipping deletion of IAM roles stack because --no-delete option is set")


@pytest.fixture(scope="session")
def api_uri(request):
    return request.config.getoption("api_uri")


@pytest.fixture(scope="class")
def api_definition_s3_uri(request, resource_bucket):
    if request.config.getoption("api_definition_s3_uri"):
        return request.config.getoption("api_definition_s3_uri")
    return (
        f"s3://{resource_bucket}/parallelcluster/{get_installed_parallelcluster_version()}/"
        f"api/ParallelCluster.openapi.yaml"
    )


@pytest.fixture(scope="class")
def api_permissions_boundary_policy_arn(request, region):
    """Return the ARN of an IAM permissions boundary to be used with the ParallelCluster API."""
    arn_partition = get_arn_partition(region)
    # TODO Restrict the permissions boundary to the minimum set of required permissions
    return f"arn:{arn_partition}:iam::aws:policy/AdministratorAccess"


@pytest.fixture(scope="session")
def api_infrastructure_s3_uri(request):
    return request.config.getoption("api_infrastructure_s3_uri")


@pytest.fixture(scope="session")
def cluster_custom_resource_service_token(request):
    return request.config.getoption("cluster_custom_resource_service_token")


@pytest.fixture(scope="session")
def lambda_layer_source(request):
    return request.config.getoption("lambda_layer_source")


@pytest.fixture(scope="class")
def s3_bucket_factory(request, region):
    """
    Define a fixture to create S3 buckets.
    :param region: region where the test is running
    :return: a function to create buckets.
    """
    created_buckets = []

    def _create_bucket():
        option = "bucket_name"
        if request.config.getoption(option):
            bucket_name = request.config.getoption(option)
            logging.info("Using existing S3 bucket {0}".format(bucket_name))
        else:
            bucket_name = "integ-tests-" + random_alphanumeric()
            logging.info("Creating S3 bucket {0}".format(bucket_name))
            create_s3_bucket(bucket_name, region)
            created_buckets.append((bucket_name, region))
        return bucket_name

    yield _create_bucket

    for bucket in created_buckets:
        if request.config.getoption("no_delete"):
            logging.info(f"Not deleting S3 bucket {bucket[0]}")
        else:
            logging.info(f"Deleting S3 bucket {bucket[0]}")
            try:
                delete_s3_bucket(bucket_name=bucket[0], region=bucket[1])
            except Exception as e:
                logging.error(f"Failed deleting bucket {bucket[0]} with exception: {e}")


@xdist_session_fixture(autouse=True)
def s3_bucket_factory_shared(request):
    """
    Define a fixture to create S3 buckets, shared among session. One bucket per region will be created.
    :return: a dictionary of buckets with region as key
    """

    created_buckets = []

    def _create_bucket(region):
        option = "bucket_name"
        if request.config.getoption(option):
            bucket_name = request.config.getoption(option)
            logging.info("Using existing S3 bucket {0}".format(bucket_name))
        else:
            bucket_name = "integ-tests-" + random_alphanumeric()
            logging.info("Creating S3 bucket {0}".format(bucket_name))
            create_s3_bucket(bucket_name, region)
            created_buckets.append((bucket_name, region))
        return bucket_name

    regions = request.config.getoption("regions") or get_all_regions(request.config.getoption("tests_config"))
    s3_buckets_dict = {}
    for region in regions:
        # region may contain an az_id if an override was specified
        # here we ensure that we are using the region
        region = unmarshal_az_override(region)
        with aws_credential_provider(region, request.config.getoption("credential")):
            s3_buckets_dict[region] = _create_bucket(region)

    yield s3_buckets_dict

    for bucket in created_buckets:
        if request.config.getoption("no_delete"):
            logging.info(f"Not deleting S3 bucket {bucket[0]}")
        else:
            logging.info(f"Deleting S3 bucket {bucket[0]}")
            try:
                with aws_credential_provider(region, request.config.getoption("credential")):
                    delete_s3_bucket(bucket_name=bucket[0], region=bucket[1])
            except Exception as e:
                logging.error(f"Failed deleting bucket {bucket[0]} with exception: {e}")


@pytest.fixture(scope="class")
def s3_bucket(s3_bucket_factory_shared, region):
    return s3_bucket_factory_shared.get(region)


@pytest.fixture(scope="class")
def s3_bucket_key_prefix():
    return random_alphanumeric()


@pytest.fixture(scope="class")
def serial_execution_by_instance(request, instance):
    """Enforce serial execution of tests, according to the adopted instance."""
    if instance in ["c5n.18xlarge", "p4d.24xlarge"]:
        logging.info("Enforcing serial execution for instance %s", instance)
        outdir = request.config.getoption("output_dir")
        lock_file = f"{outdir}/{instance}.lock"
        lock = FileLock(lock_file=lock_file)
        logging.info("Acquiring lock file %s", lock.lock_file)
        with lock.acquire(poll_interval=15, timeout=12000):
            logging.info(f"The lock is acquired by worker ID {get_xdist_worker_id(request)}: {os.getpid()}")
            yield
        logging.info(f"Releasing lock file {lock.lock_file} by {get_xdist_worker_id(request)}: {os.getpid()}")
        lock.release()
    else:
        logging.info("Ignoring serial execution for instance %s", instance)
        yield


@pytest.fixture()
def architecture(request, instance, region):
    """Return a string describing the architecture supported by the given instance type."""
    supported_architecture = request.config.cache.get(f"{instance}/architecture", None)
    if supported_architecture is None:
        logging.info(f"Getting supported architecture for instance type {instance}")
        supported_architecture = get_architecture_supported_by_instance_type(instance, region)
        request.config.cache.set(f"{instance}/architecture", supported_architecture)
    return supported_architecture


@pytest.fixture()
def network_interfaces_count(request, instance, region):
    """Return the number of network interfaces for the given instance type."""
    network_interfaces_count = request.config.cache.get(f"{instance}/network_interfaces_count", None)
    if network_interfaces_count is None:
        logging.info(f"Getting number of network interfaces for instance type {instance}")
        network_interfaces_count = get_network_interfaces_count(instance, region)
        request.config.cache.set(f"{instance}/network_interfaces_count", network_interfaces_count)
    return network_interfaces_count


@pytest.fixture(scope="class")
def placement_group_stack(cfn_stacks_factory, request, region):
    """Placement group stack contains a placement group."""
    placement_group_template = Template()
    placement_group_template.set_version()
    placement_group_template.set_description("Placement group stack created for testing existing placement group")
    placement_group_template.add_resource(PlacementGroup("PlacementGroup", Strategy="cluster"))
    stack = CfnStack(
        name=generate_stack_name("integ-tests-placement-group", request.config.getoption("stackname_suffix")),
        region=region,
        template=placement_group_template.to_json(),
    )
    cfn_stacks_factory.create_stack(stack)

    yield stack

    cfn_stacks_factory.delete_stack(stack.name, region)


def _odcr_azs(vpc_stack):
    public_subnet = vpc_stack.get_public_subnet()
    public_subnets = vpc_stack.get_all_public_subnets()
    default_public_az = boto3.resource("ec2").Subnet(public_subnet).availability_zone
    availability_zone_1 = boto3.resource("ec2").Subnet(public_subnets[0]).availability_zone
    availability_zone_2 = boto3.resource("ec2").Subnet(public_subnets[1]).availability_zone

    return {"default_public_az": default_public_az, "az1": availability_zone_1, "az2": availability_zone_2}


@pytest.fixture(scope="class")
def scaling_odcr_stack(
    request,
    region,
    os,
    cfn_stacks_factory,
    vpc_stack: CfnVpcStack,
):
    """
    Stack to deploy a capacity reservation group containing 2 ODCRs used when testing scaling involving 1000+ instances
    A single ODCR has a limit of 1000 instances.
    The number of nodes needed is distributed evenly between the 2 ODCRs.
    TODO: Allow the caller to reserve more than 2000 instances (i.e. more than 2 ODCRs).
    """
    odcr_stack: Union[CfnStack, None] = None

    def _scaling_odcr_stack(instances_count: int):
        nonlocal odcr_stack

        logging.info("Setting up the ODCR stack for scaling with special cases")
        odcr_template = Template()
        odcr_template.set_version()
        odcr_template.set_description("ODCR stack to test scaling with special cases")
        default_public_az, availability_zone_1, availability_zone_2 = _odcr_azs(vpc_stack).values()

        instance_platform = "Red Hat Enterprise Linux" if "rhel" in os else "Linux/UNIX"
        first_odcr_instances_count = int(instances_count // 2)
        scaling_odcr_a = ec2.CapacityReservation(
            "integTestsScalingOdcrA",
            AvailabilityZone=default_public_az,
            InstanceCount=first_odcr_instances_count,
            InstancePlatform=instance_platform,
            InstanceType="c5.large",
            InstanceMatchCriteria="targeted",
        )
        scaling_odcr_b = ec2.CapacityReservation(
            "integTestsScalingOdcrB",
            AvailabilityZone=default_public_az,
            InstanceCount=instances_count - first_odcr_instances_count,
            InstancePlatform=instance_platform,
            InstanceType="c5.large",
            InstanceMatchCriteria="targeted",
        )

        scaling_odcr_group = resourcegroups.Group(
            "integTestsScalingOdcrGroup",
            Name=generate_stack_name("integ-tests-odcr-group", request.config.getoption("stackname_suffix")),
            Configuration=[
                resourcegroups.ConfigurationItem(Type="AWS::EC2::CapacityReservationPool"),
                resourcegroups.ConfigurationItem(
                    Type="AWS::ResourceGroups::Generic",
                    Parameters=[
                        resourcegroups.ConfigurationParameter(
                            Name="allowed-resource-types", Values=["AWS::EC2::CapacityReservation"]
                        )
                    ],
                ),
            ],
            Resources=[
                Sub(
                    "arn:${partition}:ec2:${region}:${account_id}:capacity-reservation/${odcr_id}",
                    partition=get_arn_partition(region),
                    region=region,
                    account_id=Ref("AWS::AccountId"),
                    odcr_id=Ref(scaling_odcr_a),
                ),
                Sub(
                    "arn:${partition}:ec2:${region}:${account_id}:capacity-reservation/${odcr_id}",
                    partition=get_arn_partition(region),
                    region=region,
                    account_id=Ref("AWS::AccountId"),
                    odcr_id=Ref(scaling_odcr_b),
                ),
            ],
        )

        odcr_template.add_resource(scaling_odcr_a)
        odcr_template.add_resource(scaling_odcr_b)
        odcr_template.add_resource(scaling_odcr_group)

        stack = CfnStack(
            name=generate_stack_name("integ-tests-scaling-odcr", request.config.getoption("stackname_suffix")),
            region=region,
            template=odcr_template.to_json(),
        )
        cfn_stacks_factory.create_stack(stack)
        odcr_stack = stack
        return stack

    yield _scaling_odcr_stack

    if odcr_stack:
        cfn_stacks_factory.delete_stack(odcr_stack.name, region)


@pytest.fixture(scope="class")
def odcr_stack(
    request,
    region,
    os,
    placement_group_stack,
    cfn_stacks_factory,
    vpc_stack: CfnVpcStack,
):
    # TODO: Refactor this stack (and tests using it) to select which specific ODCRs are needed instead of having a
    #  monolithic stack with ALL ODCRs
    logging.info("Setting up the ODCR stack")
    odcr_template = Template()
    odcr_template.set_version()
    odcr_template.set_description("ODCR stack to test open, targeted, and PG ODCRs")
    default_public_az, availability_zone_1, availability_zone_2 = _odcr_azs(vpc_stack).values()

    instance_platform = "Red Hat Enterprise Linux" if "rhel" in os else "Linux/UNIX"

    open_odcr = ec2.CapacityReservation(
        "integTestsOpenOdcr",
        AvailabilityZone=default_public_az,
        InstanceCount=6,
        InstancePlatform=instance_platform,
        InstanceType="m5.2xlarge",
    )
    target_odcr = ec2.CapacityReservation(
        "integTestsTargetOdcr",
        AvailabilityZone=default_public_az,
        InstanceCount=6,
        InstancePlatform=instance_platform,
        InstanceType="r5.xlarge",
        InstanceMatchCriteria="targeted",
    )
    pg_name = placement_group_stack.cfn_resources["PlacementGroup"]
    pg_odcr = ec2.CapacityReservation(
        "integTestsPgOdcr",
        AvailabilityZone=default_public_az,
        InstanceCount=3,
        InstancePlatform=instance_platform,
        InstanceType="m5.xlarge",
        InstanceMatchCriteria="targeted",
        PlacementGroupArn=boto3.resource("ec2").PlacementGroup(pg_name).group_arn,
    )

    odcr_group = resourcegroups.Group(
        "integTestsOdcrGroup",
        Name=generate_stack_name("integ-tests-odcr-group", request.config.getoption("stackname_suffix")),
        Configuration=[
            resourcegroups.ConfigurationItem(Type="AWS::EC2::CapacityReservationPool"),
            resourcegroups.ConfigurationItem(
                Type="AWS::ResourceGroups::Generic",
                Parameters=[
                    resourcegroups.ConfigurationParameter(
                        Name="allowed-resource-types", Values=["AWS::EC2::CapacityReservation"]
                    )
                ],
            ),
        ],
        Resources=[
            Sub(
                "arn:${partition}:ec2:${region}:${account_id}:capacity-reservation/${odcr_id}",
                partition=get_arn_partition(region),
                region=region,
                account_id=Ref("AWS::AccountId"),
                odcr_id=Ref(open_odcr),
            ),
            Sub(
                "arn:${partition}:ec2:${region}:${account_id}:capacity-reservation/${odcr_id}",
                partition=get_arn_partition(region),
                region=region,
                account_id=Ref("AWS::AccountId"),
                odcr_id=Ref(target_odcr),
            ),
            Sub(
                "arn:${partition}:ec2:${region}:${account_id}:capacity-reservation/${odcr_id}",
                partition=get_arn_partition(region),
                region=region,
                account_id=Ref("AWS::AccountId"),
                odcr_id=Ref(pg_odcr),
            ),
        ],
    )
    # odcr resources for MultiAZ integ-tests
    az1_odcr = ec2.CapacityReservation(
        "az1Odcr",
        AvailabilityZone=availability_zone_1,
        InstanceCount=2,
        InstancePlatform=instance_platform,
        InstanceMatchCriteria="targeted",
        InstanceType="c5.xlarge",
    )
    az2_odcr = ec2.CapacityReservation(
        "az2Odcr",
        AvailabilityZone=availability_zone_2,
        InstanceCount=2,
        InstancePlatform=instance_platform,
        InstanceMatchCriteria="targeted",
        InstanceType="c5.xlarge",
    )
    multi_az_odcr_group = resourcegroups.Group(
        "multiAzOdcrGroup",
        Name=generate_stack_name("multi-az-odcr-group", request.config.getoption("stackname_suffix")),
        Configuration=[
            resourcegroups.ConfigurationItem(Type="AWS::EC2::CapacityReservationPool"),
            resourcegroups.ConfigurationItem(
                Type="AWS::ResourceGroups::Generic",
                Parameters=[
                    resourcegroups.ConfigurationParameter(
                        Name="allowed-resource-types", Values=["AWS::EC2::CapacityReservation"]
                    )
                ],
            ),
        ],
        Resources=[
            Sub(
                "arn:${partition}:ec2:${region}:${account_id}:capacity-reservation/${odcr_id}",
                partition=get_arn_partition(region),
                region=region,
                account_id=Ref("AWS::AccountId"),
                odcr_id=Ref(az1_odcr),
            ),
            Sub(
                "arn:${partition}:ec2:${region}:${account_id}:capacity-reservation/${odcr_id}",
                partition=get_arn_partition(region),
                region=region,
                account_id=Ref("AWS::AccountId"),
                odcr_id=Ref(az2_odcr),
            ),
        ],
    )
    odcr_template.add_resource(open_odcr)
    odcr_template.add_resource(target_odcr)
    odcr_template.add_resource(pg_odcr)
    odcr_template.add_resource(odcr_group)
    odcr_template.add_resource(az1_odcr)
    odcr_template.add_resource(az2_odcr)
    odcr_template.add_resource(multi_az_odcr_group)

    stack = CfnStack(
        name=generate_stack_name("integ-tests-odcr", request.config.getoption("stackname_suffix")),
        region=region,
        template=odcr_template.to_json(),
    )
    cfn_stacks_factory.create_stack(stack)

    yield stack

    cfn_stacks_factory.delete_stack(stack.name, region)


@pytest.fixture()
def default_threads_per_core(request, instance, region):
    """Return the default threads per core for the given instance type."""
    # NOTE: currently, .metal instances do not contain the DefaultThreadsPerCore
    #       attribute in their VCpuInfo section. This is a known limitation with the
    #       ec2 DescribeInstanceTypes API. For these instance types an assumption
    #       is made that if the instance's supported architectures list includes
    #       x86_64 then the default is 2, otherwise it's 1.
    logging.info(f"Getting defaul threads per core for instance type {instance}")
    instance_type_data = get_instance_info(instance, region)
    threads_per_core = instance_type_data.get("VCpuInfo", {}).get("DefaultThreadsPerCore")
    if threads_per_core is None:
        supported_architectures = instance_type_data.get("ProcessorInfo", {}).get("SupportedArchitectures", [])
        threads_per_core = 2 if "x86_64" in supported_architectures else 1
    logging.info(f"Defaul threads per core for instance type {instance} : {threads_per_core}")
    return threads_per_core


@pytest.fixture(scope="session")
def key_name(request):
    """Return the EC2 key pair name to be used."""
    return request.config.getoption("key_name")


@pytest.fixture()
def pcluster_ami_without_standard_naming(region, os, architecture):
    """
    Define a fixture to manage the creation and deletion of AMI without standard naming.

    This AMI is used to test the validation of pcluster version in Cookbook
    """
    ami_id = None

    def _pcluster_ami_without_standard_naming(version):
        nonlocal ami_id
        ami_id = retrieve_pcluster_ami_without_standard_naming(region, os, version, architecture)
        return ami_id

    yield _pcluster_ami_without_standard_naming

    if ami_id:
        client = boto3.client("ec2", region_name=region)
        client.deregister_image(ImageId=ami_id)


@pytest.fixture(scope="class")
def ami_copy(region):
    """
    Define a fixture to manage the copy and deletion of AMI.
    This AMI is used to test head node and compute node AMI update
    """
    copy_ami_id = None
    client = boto3.client("ec2", region_name=region)

    def _copy_image(image_id, test_name):
        nonlocal copy_ami_id
        copy_ami_id = client.copy_image(
            Name=f"aws-parallelcluster-copied-image-{test_name}", SourceImageId=image_id, SourceRegion=region
        ).get("ImageId")

        # Created tag for copied image to be filtered by cleanup ami pipeline
        client.create_tags(
            Resources=[f"{copy_ami_id}"],
            Tags=[
                {"Key": "parallelcluster:image_id", "Value": f"aws-parallelcluster-copied-image-{test_name}"},
                {"Key": "parallelcluster:build_status", "Value": "available"},
            ],
        )
        return copy_ami_id

    yield _copy_image

    if copy_ami_id:
        client = boto3.client("ec2", region_name=region)
        copied_image_info = client.describe_images(ImageIds=[copy_ami_id])
        logging.info("Deregister copied AMI.")
        client.deregister_image(ImageId=copy_ami_id)
        try:
            for block_device_mapping in copied_image_info.get("Images")[0].get("BlockDeviceMappings"):
                if block_device_mapping.get("Ebs"):
                    client.delete_snapshot(SnapshotId=block_device_mapping.get("Ebs").get("SnapshotId"))
        except IndexError as e:
            logging.error("Delete copied AMI snapshot failed due to %s", e)


@pytest.fixture()
def mpi_variants(architecture):
    variants = ["openmpi"]
    if architecture == "x86_64":
        variants.append("intelmpi")
    return variants


@pytest.fixture()
def run_benchmarks(request, mpi_variants, test_datadir, instance, os, region, benchmarks):
    def _run_benchmarks(remote_command_executor, scheduler_commands, **kwargs):
        function_name = request.function.__name__
        if not request.config.getoption("benchmarks"):
            logging.info("Skipped benchmarks for %s", function_name)
            return
        logging.info("Running benchmarks for %s", function_name)
        cloudwatch_client = boto3.client("cloudwatch")
        for benchmark in benchmarks:
            slots_per_instance = benchmark.get("slots_per_instance") or fetch_instance_slots(region, instance)
            for mpi_variant, num_instances in product(benchmark.get("mpi_variants"), benchmark.get("num_instances")):
                partition = benchmark.get("partition")
                metric_namespace = f"ParallelCluster/{function_name}"
                dimensions = {
                    "MpiVariant": mpi_variant,
                    "NumInstances": num_instances,
                    "Instance": instance,
                    "Os": os,
                    "Partition": partition,
                }
                for key, value in kwargs.items():
                    # Additional keyword arguments are put into dimensions
                    dimensions[to_pascal_case(key)] = value

                osu_benchmarks = benchmark.get("osu_benchmarks", [])
                if osu_benchmarks:
                    logging.info("Running OSU benchmarks for %s", function_name)
                    metric_data_list = run_osu_benchmarks(
                        osu_benchmarks,
                        mpi_variant,
                        partition,
                        remote_command_executor,
                        scheduler_commands,
                        num_instances,
                        slots_per_instance,
                        region,
                        instance,
                        test_datadir,
                        dimensions,
                    )
                    for metric_data in metric_data_list:
                        cloudwatch_client.put_metric_data(Namespace=metric_namespace, MetricData=metric_data)
        logging.info("Finished benchmarks for %s", function_name)

    yield _run_benchmarks


@pytest.fixture()
def test_custom_config(request):
    feature, test_id = request.node.nodeid.split("/", 1)
    test_id = test_id.split("[", 1)[0]
    tests_config = request.config.getoption("tests_config")
    if tests_config:
        return tests_config["test-suites"][feature][test_id].get("test-config")
    return None


@pytest.fixture()
def scheduler_commands_factory(scheduler):
    return partial(get_scheduler_commands, scheduler=scheduler)


@pytest.fixture(scope="class")
def fsx_factory(vpc_stack: CfnVpcStack, cfn_stacks_factory, request, region, key_name):
    """
    Define a fixture to manage the creation and destruction of fsx.

    return fsx_id
    """
    created_stacks = []

    def _fsx_factory(ports, ip_protocols, file_system_type, num=1, vpc=None, subnet=None, **kwargs):
        # FSx stack
        if num == 0:
            return []
        fsx_template = Template()
        fsx_template.set_version()
        fsx_template.set_description("Create FSx stack")

        # Create security group. If using an existing file system
        # It must be associated to a security group that allows inbound TCP/UDP traffic to specific ports
        if not vpc:
            vpc = vpc_stack.cfn_outputs["VpcId"]
            subnet = vpc_stack.get_public_subnet()
        fsx_sg = ec2.SecurityGroup(
            "FSxSecurityGroup",
            GroupDescription="SecurityGroup for testing existing FSx",
            SecurityGroupIngress=[
                ec2.SecurityGroupRule(IpProtocol=ip_protocol, FromPort=port, ToPort=port, CidrIp="0.0.0.0/0")
                for port in ports
                for ip_protocol in ip_protocols
            ],
            VpcId=vpc,
        )
        fsx_template.add_resource(fsx_sg)
        file_system_resource_name = "FileSystemResource"
        max_concurrency = 15
        for i in range(num):
            depends_on_arg = {}
            if i >= max_concurrency:
                depends_on_arg = {"DependsOn": [f"{file_system_resource_name}{i - max_concurrency}"]}
            fsx_filesystem = FileSystem(
                title=f"{file_system_resource_name}{i}",
                SecurityGroupIds=[Ref(fsx_sg)],
                SubnetIds=[subnet],
                FileSystemType=file_system_type,
                **kwargs,
                **depends_on_arg,
            )
            fsx_template.add_resource(fsx_filesystem)
        fsx_stack = CfnStack(
            name=generate_stack_name("integ-tests-fsx", request.config.getoption("stackname_suffix")),
            region=region,
            template=fsx_template.to_json(),
        )
        cfn_stacks_factory.create_stack(fsx_stack)
        created_stacks.append(fsx_stack)
        return [fsx_stack.cfn_resources[f"{file_system_resource_name}{i}"] for i in range(num)]

    yield _fsx_factory

    if not request.config.getoption("no_delete"):
        for stack in created_stacks:
            cfn_stacks_factory.delete_stack(stack.name, region)


@pytest.fixture(scope="class")
def svm_factory(vpc_stack, cfn_stacks_factory, request, region, key_name):
    """
    Define a fixture to manage the creation and destruction of storage virtual machine for FSx for Ontap.

    return volume ids
    """
    created_stacks = []

    def _svm_factory(file_system_id, num_volumes=1):
        # SVM stack
        fsx_svm_template = Template()
        fsx_svm_template.set_version()
        fsx_svm_template.set_description("Create Storage Virtual Machine stack")

        fsx_svm = StorageVirtualMachine(
            title="StorageVirtualMachineFileSystemResource", Name="fsx", FileSystemId=file_system_id
        )
        fsx_svm_template.add_resource(fsx_svm)

        svm_volume_resource_name = "SVMVolume"
        max_concurrency = 15
        for index in range(num_volumes):
            depends_on_arg = {}
            if index >= max_concurrency:
                depends_on_arg = {"DependsOn": [f"{svm_volume_resource_name}{index - max_concurrency}"]}
            fsx_svm_volume = Volume(
                title=f"{svm_volume_resource_name}{index}",
                Name=f"vol{index}",
                VolumeType="ONTAP",
                OntapConfiguration=VolumeOntapConfiguration(
                    JunctionPath=f"/vol{index}",
                    SizeInMegabytes="10240",
                    StorageEfficiencyEnabled="true",
                    StorageVirtualMachineId=Ref(fsx_svm),
                ),
                **depends_on_arg,
            )
            fsx_svm_template.add_resource(fsx_svm_volume)
        fsx_stack = CfnStack(
            name=generate_stack_name("integ-tests-fsx-svm", request.config.getoption("stackname_suffix")),
            region=region,
            template=fsx_svm_template.to_json(),
        )
        cfn_stacks_factory.create_stack(fsx_stack)
        created_stacks.append(fsx_stack)
        return [fsx_stack.cfn_resources[f"{svm_volume_resource_name}{i}"] for i in range(num_volumes)]

    yield _svm_factory

    if not request.config.getoption("no_delete"):
        for stack in created_stacks:
            cfn_stacks_factory.delete_stack(stack.name, region)


@pytest.fixture(scope="class")
def open_zfs_volume_factory(vpc_stack, cfn_stacks_factory, request, region, key_name):
    """
    Define a fixture to manage the creation and destruction of volumes for FSx for OpenZFS.

    return volume ids
    """
    created_stacks = []

    def _open_zfs_volume_factory(root_volume_id, num_volumes=1):
        fsx_open_zfs_volume_template = Template()
        fsx_open_zfs_volume_template.set_version()
        fsx_open_zfs_volume_template.set_description("Create Storage Virtual Machine stack")

        open_zfs_volume_resource_name = "OpenZFSVolume"
        max_concurrency = 15
        for index in range(num_volumes):
            depends_on_arg = {}
            if index >= max_concurrency:
                depends_on_arg = {"DependsOn": [f"{open_zfs_volume_resource_name}{index - max_concurrency}"]}
            fsx_open_zfs_volume = Volume(
                title=f"{open_zfs_volume_resource_name}{index}",
                Name=f"vol{index}",
                VolumeType="OPENZFS",
                OpenZFSConfiguration=VolumeOpenZFSConfiguration(
                    NfsExports=[
                        NfsExports(
                            ClientConfigurations=[
                                ClientConfigurations(Clients="*", Options=["rw", "crossmnt", "no_root_squash"])
                            ]
                        )
                    ],
                    ParentVolumeId=root_volume_id,
                ),
                **depends_on_arg,
            )
            fsx_open_zfs_volume_template.add_resource(fsx_open_zfs_volume)
        fsx_stack = CfnStack(
            name=generate_stack_name("integ-tests-fsx-openzfs-volume", request.config.getoption("stackname_suffix")),
            region=region,
            template=fsx_open_zfs_volume_template.to_json(),
        )
        cfn_stacks_factory.create_stack(fsx_stack)
        created_stacks.append(fsx_stack)
        return [fsx_stack.cfn_resources[f"{open_zfs_volume_resource_name}{i}"] for i in range(num_volumes)]

    yield _open_zfs_volume_factory

    if not request.config.getoption("no_delete"):
        for stack in created_stacks:
            cfn_stacks_factory.delete_stack(stack.name, region)


@pytest.fixture(scope="class")
def snapshots_factory(region):
    factory = EBSSnapshotsFactory()
    yield factory
    factory.release_all(region)


@pytest.fixture(scope="class")
def efs_stack_factory(cfn_stacks_factory, request, region, vpc_stack):
    """EFS stack contains a single efs resource."""
    created_stacks = []

    def create_efs(num=1):
        efs_template = Template()
        efs_template.set_version("2010-09-09")
        efs_template.set_description("EFS stack created for testing existing EFS")
        file_system_resource_name = "FileSystemResource"
        for i in range(num):
            efs_template.add_resource(EFSFileSystem(f"{file_system_resource_name}{i}"))
        stack_name = generate_stack_name("integ-tests-efs", request.config.getoption("stackname_suffix"))
        stack = CfnStack(name=stack_name, region=region, template=efs_template.to_json())
        cfn_stacks_factory.create_stack(stack)
        created_stacks.append(stack)
        return [stack.cfn_resources[f"{file_system_resource_name}{i}"] for i in range(num)]

    yield create_efs

    if not request.config.getoption("no_delete"):
        for stack in created_stacks:
            cfn_stacks_factory.delete_stack(stack.name, region)


@pytest.fixture(scope="class")
def efs_access_point_stack_factory(cfn_stacks_factory, request, region, vpc_stack):
    """EFS stack contains a single efs and a single access point resource."""
    created_stacks = []

    def create_access_points(efs_fs_id, num=1):
        ap_template = Template()
        ap_template.set_version("2010-09-09")
        ap_template.set_description("Access Point stack created for testing existing EFS wtith Access points")
        access_point_resource_name = "AccessPointResourceResource"
        for i in range(num):
            access_point = EFSAccessPoint(f"{access_point_resource_name}{i}")
            access_point.FileSystemId = efs_fs_id
            ap_template.add_resource(access_point)
        stack_name = generate_stack_name("integ-tests-efs-ap", request.config.getoption("stackname_suffix"))
        stack = CfnStack(name=stack_name, region=region, template=ap_template.to_json())
        cfn_stacks_factory.create_stack(stack)
        created_stacks.append(stack)
        return [stack.cfn_resources[f"{access_point_resource_name}{i}"] for i in range(num)]

    yield create_access_points

    if not request.config.getoption("no_delete"):
        for stack in created_stacks:
            cfn_stacks_factory.delete_stack(stack.name, region)


@pytest.fixture(scope="class")
def efs_mount_target_stack_factory(cfn_stacks_factory, request, region, vpc_stack):
    """
    EFS mount target stack.

    Create mount targets in all availability zones of vpc_stack
    """
    created_stacks = []

    def create_mount_targets(efs_ids):
        template = Template()
        template.set_version("2010-09-09")
        template.set_description("Mount targets stack")

        # Create a security group that allows all communication between the mount targets and instances in the VPC
        vpc_id = vpc_stack.cfn_outputs["VpcId"]
        security_group = template.add_resource(
            ec2.SecurityGroup(
                "SecurityGroupResource", GroupDescription="custom security group for EFS mount targets", VpcId=vpc_id
            )
        )
        # Allow inbound connection though NFS port within the VPC
        cidr_block_association_set = boto3.client("ec2").describe_vpcs(VpcIds=[vpc_id])["Vpcs"][0][
            "CidrBlockAssociationSet"
        ]
        for index, cidr_block_association in enumerate(cidr_block_association_set):
            vpc_cidr = cidr_block_association["CidrBlock"]
            template.add_resource(
                ec2.SecurityGroupIngress(
                    f"SecurityGroupIngressResource{index}",
                    IpProtocol="-1",
                    FromPort=2049,
                    ToPort=2049,
                    CidrIp=vpc_cidr,
                    GroupId=Ref(security_group),
                )
            )

        # Create mount targets
        subnet_ids = vpc_stack.get_all_public_subnets() + vpc_stack.get_all_private_subnets()
        _add_mount_targets(subnet_ids, efs_ids, security_group, template)

        stack_name = generate_stack_name("integ-tests-mount-targets", request.config.getoption("stackname_suffix"))
        stack = CfnStack(name=stack_name, region=region, template=template.to_json())
        cfn_stacks_factory.create_stack(stack)
        created_stacks.append(stack)
        return stack.name

    yield create_mount_targets

    if not request.config.getoption("no_delete"):
        for stack in created_stacks:
            cfn_stacks_factory.delete_stack(stack.name, region)


def _add_mount_targets(subnet_ids, efs_ids, security_group, template):
    subnet_response = boto3.client("ec2").describe_subnets(SubnetIds=subnet_ids)["Subnets"]
    for efs_index, efs_id in enumerate(efs_ids):
        availability_zones_with_mount_target = set()
        for mount_target in boto3.client("efs").describe_mount_targets(FileSystemId=efs_id)["MountTargets"]:
            availability_zones_with_mount_target.add(mount_target["AvailabilityZoneName"])
        for subnet_index, subnet in enumerate(subnet_response):
            if subnet["AvailabilityZone"] not in availability_zones_with_mount_target:
                # One and only one mount target should be created in each availability zone.
                depends_on_arg = {}
                resources = list(template.resources.keys())
                max_concurrency = 10
                if len(resources) >= max_concurrency:
                    # Create at most 10 resources in parallel.
                    depends_on_arg = {"DependsOn": [resources[-max_concurrency]]}
                template.add_resource(
                    MountTarget(
                        f"MountTargetResourceEfs{efs_index}Subnet{subnet_index}",
                        FileSystemId=efs_id,
                        SubnetId=subnet["SubnetId"],
                        SecurityGroups=[Ref(security_group)],
                        **depends_on_arg,
                    )
                )
                availability_zones_with_mount_target.add(subnet["AvailabilityZone"])


@pytest.fixture(scope="class")
def delete_storage_on_teardown(request, region):
    supported_storage_types = [StorageType.STORAGE_EBS, StorageType.STORAGE_EFS, StorageType.STORAGE_FSX]
    delete_storage_function = {
        StorageType.STORAGE_EBS: delete_ebs_volume,
        StorageType.STORAGE_EFS: delete_efs_filesystem,
        StorageType.STORAGE_FSX: delete_fsx_filesystem,
    }
    storage_resources = {storage_type: set() for storage_type in supported_storage_types}

    def _add_storage(storage_type: StorageType, storage_id: str):
        logging.info(
            f"Adding storage for deletion on teardown: storage of type {storage_type.name} with id {storage_id}"
        )
        storage_resources[storage_type].add(storage_id)

    def _delete_storage_resources():
        logging.info("Deleting storage resource on teardown")
        for storage_type, storage_ids in storage_resources.items():
            for storage_id in storage_ids:
                delete_storage_function[storage_type](region, storage_id)

    yield _add_storage

    if request.config.getoption("no_delete"):
        logging.info("Not deleting storage resources marked for removal because --no-delete option was specified")
    else:
        _delete_storage_resources()


@pytest.fixture(scope="class")
def store_secret_in_secret_manager(request, cfn_stacks_factory):
    secret_arns = {}

    def _store_secret(region, secret_string=None, secret_binary=None):
        secrets_manager_client = boto3.client("secretsmanager")
        if secret_string is None and secret_binary is None:
            logging.error("secret string and scecret binary can not both be empty")
        secret_name = generate_stack_name("integ-tests-secret", request.config.getoption("stackname_suffix"))
        if secret_string:
            secret_arn = secrets_manager_client.create_secret(Name=secret_name, SecretString=secret_string)["ARN"]
        else:
            secret_arn = secrets_manager_client.create_secret(Name=secret_name, SecretBinary=secret_binary)["ARN"]
        if secret_arns.get(region):
            secret_arns[region].append(secret_arn)
        else:
            secret_arns[region] = [secret_arn]
        return secret_arn

    yield _store_secret

    if request.config.getoption("no_delete"):
        logging.info("Not deleting stack secrets because --no-delete option was specified")
    else:
        for region, secrets in secret_arns.items():
            secrets_manager_client = boto3.client("secretsmanager", region_name=region)
            for secret_arn in secrets:
                logging.info("Deleting secret %s", secret_arn)
                secrets_manager_client.delete_secret(SecretId=secret_arn)
