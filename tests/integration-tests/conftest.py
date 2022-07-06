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

import json
import logging
import os
import random
import re
from functools import partial
from itertools import product
from pathlib import Path
from shutil import copyfile
from traceback import format_tb
from typing import Any, Optional, Tuple

import boto3
import pytest
import yaml
from _pytest.fixtures import FixtureDef, SubRequest
from cfn_stacks_factory import CfnStack, CfnStacksFactory
from clusters_factory import Cluster, ClustersFactory
from conftest_markers import (
    DIMENSIONS_MARKER_ARGS,
    add_default_markers,
    check_marker_dimensions,
    check_marker_list,
    check_marker_skip_dimensions,
    check_marker_skip_list,
)
from conftest_tests_config import apply_cli_dimensions_filtering, parametrize_from_config, remove_disabled_tests
from constants import SCHEDULERS_SUPPORTING_IMDS_SECURED
from filelock import FileLock
from framework.credential_providers import aws_credential_provider, register_cli_credentials_for_region
from framework.fixture_utils import xdist_session_fixture
from framework.tests_configuration.config_renderer import read_config_file
from framework.tests_configuration.config_utils import get_all_regions
from images_factory import Image, ImagesFactory
from jinja2 import Environment, FileSystemLoader
from network_template_builder import Gateways, NetworkTemplateBuilder, SubnetConfig, VPCConfig
from retrying import retry
from troposphere import Ref, Template, ec2
from troposphere.ec2 import PlacementGroup
from troposphere.fsx import FileSystem, StorageVirtualMachine, Volume, VolumeOntapConfiguration
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
    get_network_interfaces_count,
    get_vpc_snakecase_value,
    random_alphanumeric,
    scheduler_plugin_definition_uploader,
    set_logger_formatter,
)

from tests.common.osu_common import run_osu_benchmarks
from tests.common.schedulers_common import get_scheduler_commands
from tests.common.utils import (
    fetch_instance_slots,
    get_installed_parallelcluster_version,
    retrieve_pcluster_ami_without_standard_naming,
)


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
    parser.addoption("--public-ecr-image-uri", help="S3 URI of the ParallelCluster API spec")
    parser.addoption(
        "--api-definition-s3-uri", help="URI of the Docker image for the Lambda of the ParallelCluster API"
    )
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
    parser.addoption("--benchmarks", action="store_true", default=False, help="enable benchmark tests")
    parser.addoption("--stackname-suffix", help="set a suffix in the integration tests stack names")
    parser.addoption(
        "--delete-logs-on-success", help="delete CloudWatch logs when a test succeeds", action="store_true"
    )
    parser.addoption(
        "--use-default-iam-credentials",
        help="use default IAM creds when running pcluster commands",
        action="store_true",
    )
    parser.addoption(
        "--iam-user-role-stack-name",
        help="Name of CFN stack providing IAM user roles.",
    )
    parser.addoption(
        "--directory-stack-name",
        help="Name of CFN stack providing AD domain to be used for testing AD integration feature.",
    )
    parser.addoption(
        "--ldaps-nlb-stack-name",
        help="Name of CFN stack providing NLB to enable use of LDAPS with a Simple AD directory when testing AD "
        "integration feature.",
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
        config.option.tests_config = read_config_file(config.getoption("tests_config_file"))

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


def pytest_sessionstart(session):
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


def pytest_runtest_logstart(nodeid: str, location: Tuple[str, Optional[int], str]):
    """Called to execute the test item."""
    test_name = location[2]
    set_logger_formatter(
        logging.Formatter(fmt=f"%(asctime)s - %(levelname)s - %(process)d - {test_name} - %(module)s - %(message)s")
    )
    logging.info("Running test %s", test_name)


def pytest_runtest_logfinish(nodeid: str, location: Tuple[str, Optional[int], str]):
    logging.info("Completed test %s", location[2])
    set_logger_formatter(logging.Formatter(fmt="%(asctime)s - %(levelname)s - %(process)d - %(module)s - %(message)s"))


def pytest_runtest_setup(item):
    logging.info("Starting setup for test %s", item.name)


def pytest_runtest_teardown(item, nextitem):
    logging.info("Starting teardown for test %s", item.name)


def pytest_fixture_setup(fixturedef: FixtureDef[Any], request: SubRequest) -> Optional[object]:
    logging.info("Setting up fixture %s", fixturedef)
    return None


def pytest_collection_modifyitems(session, config, items):
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

    _add_filename_markers(items, config)


def pytest_collection_finish(session):
    _log_collected_tests(session)


def _log_collected_tests(session):
    from xdist import get_xdist_worker_id

    # Write collected tests in a single worker
    # get_xdist_worker_id returns the id of the current worker ('gw0', 'gw1', etc) or 'master'
    if get_xdist_worker_id(session) in ["master", "gw0"]:
        collected_tests = list(map(lambda item: item.nodeid, session.items))
        logging.info(
            "Collected tests in regions %s (total=%d):\n%s",
            session.config.getoption("regions") or get_all_regions(session.config.getoption("tests_config")),
            len(session.items),
            json.dumps(collected_tests, indent=2),
        )
        out_dir = session.config.getoption("output_dir")
        with open(f"{out_dir}/collected_tests.txt", "a", encoding="utf-8") as out_f:
            out_f.write("\n".join(collected_tests))
            out_f.write("\n")


def pytest_exception_interact(node, call, report):
    """Called when an exception was raised which can potentially be interactively handled.."""
    logging.error(
        "Exception raised while executing %s: %s\n%s",
        node.name,
        call.excinfo.value,
        "".join(format_tb(call.excinfo.tb)),
    )


def _extract_tested_component_from_filename(item):
    """Extract portion of test item's filename identifying the component it tests."""
    test_location = os.path.splitext(os.path.basename(item.location[0]))[0]
    return re.sub(r"test_|_test", "", test_location)


def _add_filename_markers(items, config):
    """Add a marker based on the name of the file where the test case is defined."""
    for item in items:
        marker = _extract_tested_component_from_filename(item)
        # This dynamically registers markers in pytest so that warning for the usage of undefined markers are not
        # displayed
        config.addinivalue_line("markers", marker)
        item.add_marker(marker)


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


def _add_properties_to_report(item):
    props = []

    # Add properties for test dimensions, obtained from fixtures passed to tests
    for dimension in DIMENSIONS_MARKER_ARGS:
        value = item.funcargs.get(dimension)
        if value:
            props.append((dimension, value))

    # Add property for feature tested, obtained from filename containing the test
    props.append(("feature", _extract_tested_component_from_filename(item)))

    for dimension_value_pair in props:
        if dimension_value_pair not in item.user_properties:
            item.user_properties.append(dimension_value_pair)


@pytest.fixture(scope="class")
@pytest.mark.usefixtures("setup_credentials")
def clusters_factory(request, region):
    """
    Define a fixture to manage the creation and destruction of clusters.

    The configs used to create clusters are dumped to output_dir/clusters_configs/{test_name}.config
    """
    factory = ClustersFactory(delete_logs_on_success=request.config.getoption("delete_logs_on_success"))

    def _cluster_factory(cluster_config, upper_case_cluster_name=False, **kwargs):
        cluster_config = _write_config_to_outdir(request, cluster_config, "clusters_configs")
        cluster = Cluster(
            name=request.config.getoption("cluster")
            if request.config.getoption("cluster")
            else "integ-tests-{0}{1}{2}".format(
                random_alphanumeric().upper() if upper_case_cluster_name else random_alphanumeric(),
                "-" if request.config.getoption("stackname_suffix") else "",
                request.config.getoption("stackname_suffix"),
            ),
            config_file=cluster_config,
            ssh_key=request.config.getoption("key_path"),
            region=region,
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


@pytest.fixture(scope="session")
def api_server_factory(
    cfn_stacks_factory, request, public_ecr_image_uri, api_definition_s3_uri, api_infrastructure_s3_uri
):
    """Creates a factory for deploying API servers on-demand to each region."""
    api_servers = {}

    def _api_server_factory(server_region):
        api_stack_name = generate_stack_name("integ-tests-api", request.config.getoption("stackname_suffix"))

        params = [
            {"ParameterKey": "EnableIamAdminAccess", "ParameterValue": "true"},
            {"ParameterKey": "CreateApiUserRole", "ParameterValue": "false"},
        ]
        if api_definition_s3_uri:
            params.append({"ParameterKey": "ApiDefinitionS3Uri", "ParameterValue": api_definition_s3_uri})
        if public_ecr_image_uri:
            params.append({"ParameterKey": "PublicEcrImageUri", "ParameterValue": public_ecr_image_uri})

        template = (
            api_infrastructure_s3_uri
            or f"https://{server_region}-aws-parallelcluster.s3.{server_region}.amazonaws.com"
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
            image_id="-".join([image_id, request.config.getoption("stackname_suffix")])
            if request.config.getoption("stackname_suffix")
            else image_id,
            config_file=image_config_file,
            region=region,
        )
        factory.create_image(image, **kwargs)
        if image.image_status != "BUILD_IN_PROGRESS" and kwargs.get("log_error", False):
            logging.error("image %s creation failed", image_id)

        return image

    yield _image_factory
    factory.destroy_all_images()


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
def pcluster_config_reader(test_datadir, vpc_stack, request, region, scheduler_plugin_configuration):
    """
    Define a fixture to render pcluster config templates associated to the running test.

    The config for a given test is a pcluster.config.yaml file stored in the configs_datadir folder.
    The config can be written by using Jinja2 template engine.
    The current renderer already replaces placeholders for current keys:
        {{ region }}, {{ os }}, {{ instance }}, {{ scheduler}}, {{ key_name }},
        {{ vpc_id }}, {{ public_subnet_id }}, {{ private_subnet_id }}
    The current renderer injects options for custom templates and packages in case these
    are passed to the cli and not present already in the cluster config.
    Also sanity_check is set to true by default unless explicitly set in config.

    :return: a _config_renderer(**kwargs) function which gets as input a dictionary of values to replace in the template
    """

    def _config_renderer(config_file="pcluster.config.yaml", benchmarks=None, **kwargs):
        config_file_path = test_datadir / config_file
        if not os.path.isfile(config_file_path):
            raise FileNotFoundError(f"Cluster config file not found in the expected dir {config_file_path}")
        default_values = _get_default_template_values(vpc_stack, request)
        file_loader = FileSystemLoader(str(test_datadir))
        env = Environment(loader=file_loader)
        rendered_template = env.get_template(config_file).render(**{**default_values, **kwargs})
        config_file_path.write_text(rendered_template)
        if not config_file.endswith("image.config.yaml"):
            inject_additional_config_settings(
                config_file_path, request, region, benchmarks, scheduler_plugin_configuration
            )
        else:
            inject_additional_image_configs_settings(config_file_path, request)
        return config_file_path

    return _config_renderer


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


def inject_additional_config_settings(  # noqa: C901
    cluster_config, request, region, benchmarks=None, scheduler_plugin_configuration=None
):  # noqa C901
    with open(cluster_config, encoding="utf-8") as conf_file:
        config_content = yaml.safe_load(conf_file)

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
                scheduler_prefix = "Scheduler" if scheduler == "plugin" else scheduler.capitalize()
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

    configure_scheduler_plugin(scheduler_plugin_configuration, config_content)

    with open(cluster_config, "w", encoding="utf-8") as conf_file:
        yaml.dump(config_content, conf_file)


def configure_scheduler_plugin(scheduler_plugin_configuration, config_content):
    if scheduler_plugin_configuration and not dict_has_nested_key(
        config_content, ("Scheduling", "SchedulerSettings", "SchedulerDefinition")
    ):
        dict_add_nested_key(
            config_content,
            scheduler_plugin_configuration["scheduler-definition-url"],
            ("Scheduling", "SchedulerSettings", "SchedulerDefinition"),
        )
        dict_add_nested_key(
            config_content,
            scheduler_plugin_configuration["requires-sudo"],
            ("Scheduling", "SchedulerSettings", "GrantSudoPrivileges"),
        )


def _add_policy_for_pre_post_install(node_config, custom_option, request, region):
    match = re.match(r"s3://(.*?)/(.*)", request.config.getoption(custom_option))
    if not match or len(match.groups()) < 2:
        logging.info("{0} script is not an S3 URL".format(custom_option))
    else:
        additional_iam_policies = {"Policy": f"arn:{get_arn_partition(region)}:iam::aws:policy/AmazonS3ReadOnlyAccess"}
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
            if dict_has_nested_key(node_config, ("Iam", "AdditionalIamPolicies")):
                if additional_iam_policies not in node_config["Iam"]["AdditionalIamPolicies"]:
                    node_config["Iam"]["AdditionalIamPolicies"].append(additional_iam_policies)
            else:
                dict_add_nested_key(node_config, [additional_iam_policies], ("Iam", "AdditionalIamPolicies"))


def _get_default_template_values(vpc_stack, request):
    """Build a dictionary of default values to inject in the jinja templated cluster configs."""
    default_values = get_vpc_snakecase_value(vpc_stack)
    default_values.update({dimension: request.node.funcargs.get(dimension) for dimension in DIMENSIONS_MARKER_ARGS})
    default_values["key_name"] = request.config.getoption("key_name")

    if default_values.get("scheduler") in request.config.getoption("tests_config", default={}).get(
        "scheduler-plugins", {}
    ):
        default_values["scheduler"] = "plugin"
    default_values["imds_secured"] = default_values.get("scheduler") in SCHEDULERS_SUPPORTING_IMDS_SECURED
    default_values["scheduler_prefix"] = {
        "slurm": "Slurm",
        "awsbatch": "AwsBatch",
        "plugin": "Scheduler",
    }.get(default_values.get("scheduler"))

    return default_values


@pytest.fixture(scope="session")
def cfn_stacks_factory(request):
    """Define a fixture to manage the creation and destruction of CloudFormation stacks."""
    factory = CfnStacksFactory(request.config.getoption("credential"))
    yield factory
    if not request.config.getoption("no_delete"):
        factory.delete_all_stacks()
    else:
        logging.warning("Skipping deletion of CFN stacks because --no-delete option is set")


@pytest.fixture()
@pytest.mark.usefixtures("setup_credentials")
def parameterized_cfn_stacks_factory(request):
    """Define a fixture that returns a parameterized stack factory and manages the stack creation and deletion."""
    factory = CfnStacksFactory(request.config.getoption("credential"))

    def _create_stack(region, template_path, stack_prefix="", parameters=None, capabilities=None):
        file_content = extract_template(template_path)
        stack = CfnStack(
            name=generate_stack_name(stack_prefix, request.config.getoption("stackname_suffix")),
            region=region,
            template=file_content,
            parameters=parameters or [],
            capabilities=capabilities or [],
        )
        factory.create_stack(stack)
        return stack

    def extract_template(template_path):
        with open(template_path, encoding="utf-8") as cfn_file:
            file_content = cfn_file.read()
        return file_content

    yield _create_stack
    factory.delete_all_stacks()


AVAILABILITY_ZONE_OVERRIDES = {
    # c5.xlarge is not supported in use1-az3
    # FSx Lustre file system creation is currently not supported for use1-az3
    # p4d.24xlarge targeted ODCR is only available on use1-az6
    "us-east-1": ["use1-az6"],
    # some instance type is only supported in use2-az2
    "us-east-2": ["use2-az2"],
    # c4.xlarge is not supported in usw2-az4
    "us-west-2": ["usw2-az2", "usw2-az1"],
    # c5.xlarge is not supported in apse2-az3
    "ap-southeast-2": ["apse2-az1", "apse2-az2"],
    # m6g.xlarge is not supported in apne1-az2
    "ap-northeast-1": ["apne1-az4", "apne1-az1"],
    # c4.xlarge is not supported in apne2-az2
    "ap-northeast-2": ["apne2-az1", "apne2-az3"],
    # c5.xlarge is not supported in apse1-az3
    "ap-southeast-1": ["apse1-az2", "apse1-az1"],
    # c4.xlarge is not supported in aps1-az2
    "ap-south-1": ["aps1-az1", "aps1-az3"],
    # NAT Gateway not available in sae1-az2 , c5n.18xlarge is not supported in sae1-az3
    "sa-east-1": ["sae1-az1"],
    # m6g.xlarge instances not available in euw1-az3
    "eu-west-1": ["euw1-az1", "euw1-az2"],
    # io2 EBS volumes not available in cac1-az4
    "ca-central-1": ["cac1-az1", "cac1-az2"],
    # instance can only be launch in placement group in eun1-az2
    "eu-north-1": ["eun1-az2"],
    # g3.8xlarge is not supported in euc1-az1
    "eu-central-1": ["euc1-az2", "euc1-az3"],
    # FSx not available in cnn1-az4
    "cn-north-1": ["cnn1-az1", "cnn1-az2"],
}


@pytest.fixture(scope="function")
def random_az_selector(request):
    """Select random AZs for a given region."""

    def _get_random_availability_zones(region, num_azs=1, default_value=None):
        """Return num_azs random AZs (in the form of AZ names, e.g. 'us-east-1a') for the given region."""
        az_ids = AVAILABILITY_ZONE_OVERRIDES.get(region, [])
        if az_ids:
            az_id_to_az_name_map = get_az_id_to_az_name_map(region, request.config.getoption("credential"))
            sample = random.sample([az_id_to_az_name_map.get(az_id, default_value) for az_id in az_ids], k=num_azs)
        else:
            sample = [default_value] * num_azs
        return sample[0] if num_azs == 1 else sample

    return _get_random_availability_zones


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


def get_az_id_to_az_name_map(region, credential):
    """Return a dict mapping AZ IDs (e.g, 'use1-az2') to AZ names (e.g., 'us-east-1c')."""
    # credentials are managed manually rather than via setup_sts_credentials because this function
    # is called by a session-scoped fixture, which cannot make use of a class-scoped fixture.
    with aws_credential_provider(region, credential):
        ec2_client = boto3.client("ec2", region_name=region)
        return {
            entry.get("ZoneId"): entry.get("ZoneName")
            for entry in ec2_client.describe_availability_zones().get("AvailabilityZones")
        }


def get_availability_zones(region, credential):
    """
    Return a list of availability zones for the given region.

    Note that this function is called by the vpc_stacks fixture. Because vcp_stacks is session-scoped,
    it cannot utilize setup_sts_credentials, which is required in opt-in regions in order to call
    describe_availability_zones.
    """
    az_list = []
    with aws_credential_provider(region, credential):
        client = boto3.client("ec2", region_name=region)
        response_az = client.describe_availability_zones(
            Filters=[
                {"Name": "region-name", "Values": [str(region)]},
                {"Name": "zone-type", "Values": ["availability-zone"]},
            ]
        )
        for az in response_az.get("AvailabilityZones"):
            az_list.append(az.get("ZoneName"))
    return az_list


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


@pytest.fixture(scope="session", autouse=True)
def vpc_stacks(cfn_stacks_factory, request):
    """Create VPC used by integ tests in all configured regions."""
    regions = request.config.getoption("regions") or get_all_regions(request.config.getoption("tests_config"))
    vpc_stacks = {}

    for region in regions:
        # Creating private_subnet_different_cidr in a different AZ for test_efs
        # To-do: isolate this logic and create a compute subnet in different AZ than head node in test_efs

        # if region has a non-empty list in AVAILABILITY_ZONE_OVERRIDES, select a subset of those AZs
        credential = request.config.getoption("credential")
        az_ids_for_region = AVAILABILITY_ZONE_OVERRIDES.get(region, [])
        if az_ids_for_region:
            az_id_to_az_name = get_az_id_to_az_name_map(region, credential)
            az_names = [az_id_to_az_name.get(az_id) for az_id in az_ids_for_region]
            # if only one AZ can be used for the given region, use it multiple times
            if len(az_names) == 1:
                az_names *= 2
            availability_zones = random.sample(az_names, k=2)
        # otherwise, select a subset of all AZs in the region
        else:
            az_list = get_availability_zones(region, credential)
            # if number of available zones is smaller than 2, available zones should be [None, None]
            if len(az_list) < 2:
                availability_zones = [None, None]
            else:
                availability_zones = random.sample(az_list, k=2)

        # Subnets visual representation:
        # http://www.davidc.net/sites/default/subnets/subnets.html?network=192.168.0.0&mask=16&division=7.70
        public_subnet = SubnetConfig(
            name="Public",
            cidr="192.168.32.0/19",  # 8190 IPs
            map_public_ip_on_launch=True,
            has_nat_gateway=True,
            availability_zone=availability_zones[0],
            default_gateway=Gateways.INTERNET_GATEWAY,
        )
        private_subnet = SubnetConfig(
            name="Private",
            cidr="192.168.64.0/18",  # 16382 IPs
            map_public_ip_on_launch=False,
            has_nat_gateway=False,
            availability_zone=availability_zones[0],
            default_gateway=Gateways.NAT_GATEWAY,
        )
        private_subnet_different_cidr = SubnetConfig(
            name="PrivateAdditionalCidr",
            cidr="192.168.128.0/17",  # 32766 IPs
            map_public_ip_on_launch=False,
            has_nat_gateway=False,
            availability_zone=availability_zones[1],
            default_gateway=Gateways.NAT_GATEWAY,
        )
        no_internet_subnet = SubnetConfig(
            name="NoInternet",
            cidr="192.168.16.0/20",  # 4094 IPs
            map_public_ip_on_launch=False,
            has_nat_gateway=False,
            availability_zone=availability_zones[0],
            default_gateway=Gateways.NONE,
        )
        vpc_config = VPCConfig(
            cidr="192.168.0.0/17",
            additional_cidr_blocks=["192.168.128.0/17"],
            subnets=[public_subnet, private_subnet, private_subnet_different_cidr, no_internet_subnet],
        )
        template = NetworkTemplateBuilder(vpc_configuration=vpc_config, availability_zone=availability_zones[0]).build()
        vpc_stacks[region] = _create_vpc_stack(request, template, region, cfn_stacks_factory)

    return vpc_stacks


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


@pytest.fixture(scope="class")
def vpc_stack(vpc_stacks, region):
    return vpc_stacks[region]


@pytest.fixture(scope="session")
def public_ecr_image_uri(request):
    return request.config.getoption("public_ecr_image_uri")


@pytest.fixture(scope="session")
def api_uri(request):
    return request.config.getoption("api_uri")


@pytest.fixture(scope="session")
def api_definition_s3_uri(request):
    return request.config.getoption("api_definition_s3_uri")


@pytest.fixture(scope="session")
def api_infrastructure_s3_uri(request):
    return request.config.getoption("api_infrastructure_s3_uri")


# If stack creation fails it'll retry once more. This is done to mitigate failures due to resources
# not available in randomly picked AZs.
@retry(
    stop_max_attempt_number=2,
    wait_fixed=5000,
    retry_on_exception=lambda exception: not isinstance(exception, KeyboardInterrupt),
)
def _create_vpc_stack(request, template, region, cfn_stacks_factory):
    if request.config.getoption("vpc_stack"):
        logging.info("Using stack {0} in region {1}".format(request.config.getoption("vpc_stack"), region))
        stack = CfnStack(name=request.config.getoption("vpc_stack"), region=region, template=template.to_json())
    else:
        stack = CfnStack(
            name=generate_stack_name("integ-tests-vpc", request.config.getoption("stackname_suffix")),
            region=region,
            template=template.to_json(),
        )
        cfn_stacks_factory.create_stack(stack)
    return stack


@pytest.fixture(scope="class")
def s3_bucket_factory(request, region):
    """
    Define a fixture to create S3 buckets.
    :param region: region where the test is running
    :return: a function to create buckets.
    """
    created_buckets = []

    def _create_bucket():
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
        bucket_name = "integ-tests-" + random_alphanumeric()
        logging.info("Creating S3 bucket {0}".format(bucket_name))
        create_s3_bucket(bucket_name, region)
        created_buckets.append((bucket_name, region))
        return bucket_name

    regions = request.config.getoption("regions") or get_all_regions(request.config.getoption("tests_config"))
    s3_buckets_dict = {}
    for region in regions:
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


@xdist_session_fixture(autouse=True)
def scheduler_plugin_definitions(s3_bucket_factory_shared, request) -> dict:
    scheduler_definition_dict = {}
    tests_config = request.config.getoption("tests_config", default={})
    if tests_config:
        plugins = tests_config.get("scheduler-plugins", {})
        for plugin_name in plugins:
            plugin = plugins.get(plugin_name)
            scheduler_definition = plugin.get("scheduler-definition")
            if os.path.isfile(scheduler_definition):
                logging.info(
                    "Found scheduler-definition (%s) for scheduler plugin (%s)", scheduler_definition, plugin_name
                )
                scheduler_definition_dict[plugin_name] = {}
                for region, s3_bucket in s3_bucket_factory_shared.items():
                    with aws_credential_provider(region, request.config.getoption("credential")):
                        scheduler_plugin_definition_url = scheduler_plugin_definition_uploader(
                            scheduler_definition, s3_bucket, plugin_name, region
                        )
                    scheduler_definition_dict[plugin_name].update({region: scheduler_plugin_definition_url})
            else:
                logging.info(
                    "Found scheduler definition (%s) for scheduler plugin (%s)", scheduler_definition, plugin_name
                )
                scheduler_definition_dict[plugin_name] = {}
                for region in s3_bucket_factory_shared.keys():
                    scheduler_definition_dict[plugin_name].update({region: scheduler_definition})

    return scheduler_definition_dict


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Making test result information available in fixtures"""
    # add dimension properties to report
    _add_properties_to_report(item)

    # execute all other hooks to obtain the report object
    outcome = yield
    rep = outcome.get_result()
    # set a report attribute for each phase of a call, which can
    # be "setup", "call", "teardown"
    setattr(item, "rep_" + rep.when, rep)

    if rep.when in ["setup", "call"] and rep.failed:
        try:
            update_failed_tests_config(item)
        except Exception as e:
            logging.error("Failed when generating config for failed tests: %s", e, exc_info=True)


def update_failed_tests_config(item):
    out_dir = Path(item.config.getoption("output_dir"))
    if not str(out_dir).endswith(".out"):
        # Navigate to the parent dir in case of parallel run so that we can access the shared parent dir
        out_dir = out_dir.parent

    out_file = out_dir / "failed_tests_config.yaml"
    logging.info("Updating failed tests config file %s", out_file)
    # We need to acquire a lock first to prevent concurrent edits to this file
    with FileLock(str(out_file) + ".lock"):
        failed_tests = {"test-suites": {}}
        if out_file.is_file():
            with open(str(out_file), encoding="utf-8") as f:
                failed_tests = yaml.safe_load(f)

        # item.node.nodeid example:
        # 'dcv/test_dcv.py::test_dcv_configuration[eu-west-1-c5.xlarge-centos7-slurm-8443-0.0.0.0/0-/shared]'
        feature, test_id = item.nodeid.split("/", 1)
        test_id = test_id.split("[", 1)[0]
        dimensions = {}
        for dimension in DIMENSIONS_MARKER_ARGS:
            value = item.callspec.params.get(dimension)
            if value:
                dimensions[dimension + "s"] = [value]

        if not dict_has_nested_key(failed_tests, ("test-suites", feature, test_id)):
            dict_add_nested_key(failed_tests, [], ("test-suites", feature, test_id, "dimensions"))
        if dimensions not in failed_tests["test-suites"][feature][test_id]["dimensions"]:
            failed_tests["test-suites"][feature][test_id]["dimensions"].append(dimensions)
            with open(out_file, "w", encoding="utf-8") as f:
                yaml.dump(failed_tests, f)


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
            Resources=[
                f"{copy_ami_id}",
            ],
            Tags=[
                {
                    "Key": "parallelcluster:image_id",
                    "Value": f"aws-parallelcluster-copied-image-{test_name}",
                },
                {
                    "Key": "parallelcluster:build_status",
                    "Value": "available",
                },
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


def to_pascal_case(snake_case_word):
    """Convert the given snake case word into a PascalCase one."""
    parts = iter(snake_case_word.split("_"))
    return "".join(word.title() for word in parts)


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
                        cloudwatch_client.put_metric_data(
                            Namespace=metric_namespace,
                            MetricData=metric_data,
                        )
        logging.info("Finished benchmarks for %s", function_name)

    yield _run_benchmarks


@pytest.fixture()
def scheduler_plugin_configuration(request, region, scheduler_plugin_definitions):
    try:
        scheduler = request.getfixturevalue("scheduler")
    except pytest.FixtureLookupError:
        scheduler = None
    scheduler_plugin = request.config.getoption("tests_config", default={}).get("scheduler-plugins", {}).get(scheduler)
    scheduler_definition_url = scheduler_plugin_definitions.get(scheduler, {}).get(region, {})
    if scheduler_definition_url:
        logging.info(
            "Adding scheduler plugin (%s) scheduler-definition-url to be (%s)",
            scheduler,
            scheduler_definition_url,
        )
        scheduler_plugin["scheduler-definition-url"] = scheduler_definition_url

    return scheduler_plugin


@pytest.fixture()
def test_custom_config(request):
    feature, test_id = request.node.nodeid.split("/", 1)
    test_id = test_id.split("[", 1)[0]
    tests_config = request.config.getoption("tests_config")
    if tests_config:
        return tests_config["test-suites"][feature][test_id].get("test-config")
    return None


@pytest.fixture()
def scheduler_commands_factory(scheduler, scheduler_plugin_configuration):
    if scheduler_plugin_configuration:
        import importlib

        scheduler_commands = scheduler_plugin_configuration["scheduler-commands"]
        logging.info("Loading scheduler commands from %s", scheduler_commands)
        try:
            module_name, class_name = scheduler_commands.rsplit(".", 1)
            return getattr(importlib.import_module(module_name), class_name)
        except Exception as e:
            logging.error("Failed when loading scheduler commands from %s: %s", scheduler_commands, e)
            raise
    else:
        return partial(get_scheduler_commands, scheduler=scheduler)


@pytest.fixture(scope="class")
def fsx_factory(vpc_stack, cfn_stacks_factory, request, region, key_name):
    """
    Define a fixture to manage the creation and destruction of fsx.

    return fsx_id
    """
    created_stacks = []

    def _fsx_factory(ports, ip_protocols, file_system_type, num=1, **kwargs):
        # FSx stack
        if num == 0:
            return []
        fsx_template = Template()
        fsx_template.set_version()
        fsx_template.set_description("Create FSx stack")

        # Create security group. If using an existing file system
        # It must be associated to a security group that allows inbound TCP/UDP traffic to specific ports
        fsx_sg = ec2.SecurityGroup(
            "FSxSecurityGroup",
            GroupDescription="SecurityGroup for testing existing FSx",
            SecurityGroupIngress=[
                ec2.SecurityGroupRule(
                    IpProtocol=ip_protocol,
                    FromPort=port,
                    ToPort=port,
                    CidrIp="0.0.0.0/0",
                )
                for port in ports
                for ip_protocol in ip_protocols
            ],
            VpcId=vpc_stack.cfn_outputs["VpcId"],
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
                SubnetIds=[vpc_stack.cfn_outputs["PublicSubnetId"]],
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
            title="StorageVirtualMachineFileSystemResource",
            Name="fsx",
            FileSystemId=file_system_id,
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
