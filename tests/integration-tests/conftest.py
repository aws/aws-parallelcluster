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
import time
from shutil import copyfile
from traceback import format_tb

import boto3
import configparser
import pkg_resources
import pytest
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
from framework.tests_configuration.config_renderer import read_config_file
from framework.tests_configuration.config_utils import get_all_regions
from jinja2 import Environment, FileSystemLoader
from network_template_builder import Gateways, NetworkTemplateBuilder, SubnetConfig, VPCConfig
from retrying import retry
from utils import (
    create_s3_bucket,
    delete_s3_bucket,
    generate_stack_name,
    get_architecture_supported_by_instance_type,
    get_network_interfaces_count,
    get_vpc_snakecase_value,
    random_alphanumeric,
    set_credentials,
    set_logger_formatter,
    unset_credentials,
)

from tests.common.utils import get_sts_endpoint, retrieve_pcluster_ami_without_standard_naming


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
        "--createami-custom-chef-cookbook", help="url to a custom cookbook package for the createami command"
    )
    parser.addoption("--createami-custom-node-package", help="url to a custom node package for the createami command")
    parser.addoption("--custom-awsbatch-template-url", help="url to a custom awsbatch template")
    parser.addoption("--template-url", help="url to a custom cfn template")
    parser.addoption("--hit-template-url", help="url to a custom HIT cfn template")
    parser.addoption("--cw-dashboard-template-url", help="url to a custom Dashboard cfn template")
    parser.addoption("--custom-awsbatchcli-package", help="url to a custom awsbatch cli package")
    parser.addoption("--custom-node-package", help="url to a custom node package")
    parser.addoption("--custom-ami", help="custom AMI to use in the tests")
    parser.addoption("--pre-install", help="url to pre install script")
    parser.addoption("--post-install", help="url to post install script")
    parser.addoption("--vpc-stack", help="Name of an existing vpc stack.")
    parser.addoption("--cluster", help="Use an existing cluster instead of creating one.")
    parser.addoption(
        "--credential", help="STS credential endpoint, in the format <region>,<endpoint>,<ARN>,<externalId>.", nargs="+"
    )
    parser.addoption(
        "--no-delete", action="store_true", default=False, help="Don't delete stacks after tests are complete."
    )
    parser.addoption("--benchmarks-target-capacity", help="set the target capacity for benchmarks tests", type=int)
    parser.addoption("--benchmarks-max-time", help="set the max waiting time in minutes for benchmarks tests", type=int)
    parser.addoption("--stackname-suffix", help="set a suffix in the integration tests stack names")
    parser.addoption(
        "--keep-logs-on-cluster-failure",
        help="preserve CloudWatch logs when a cluster fails to be created",
        action="store_true",
    )
    parser.addoption(
        "--keep-logs-on-test-failure", help="preserve CloudWatch logs when a test fails", action="store_true"
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


def pytest_runtest_call(item):
    """Called to execute the test item."""
    _add_properties_to_report(item)
    set_logger_formatter(logging.Formatter(fmt=f"%(asctime)s - %(levelname)s - {item.name} - %(module)s - %(message)s"))
    logging.info("Running test " + item.name)


def pytest_runtest_logfinish(nodeid, location):
    set_logger_formatter(logging.Formatter(fmt="%(asctime)s - %(levelname)s - %(module)s - %(message)s"))


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
        with open(f"{out_dir}/collected_tests.txt", "a") as out_f:
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
    formatter = logging.Formatter(fmt="%(asctime)s - %(levelname)s - %(module)s - %(message)s")
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
@pytest.mark.usefixtures("setup_sts_credentials")
def clusters_factory(request):
    """
    Define a fixture to manage the creation and destruction of clusters.

    The configs used to create clusters are dumped to output_dir/clusters_configs/{test_name}.config
    """
    factory = ClustersFactory(keep_logs_on_failure=request.config.getoption("keep_logs_on_cluster_failure"))

    def _cluster_factory(cluster_config, extra_args=None, raise_on_error=True):
        cluster_config = _write_cluster_config_to_outdir(request, cluster_config)
        cluster = Cluster(
            name=request.config.getoption("cluster")
            if request.config.getoption("cluster")
            else "integ-tests-{0}{1}{2}".format(
                random_alphanumeric(),
                "-" if request.config.getoption("stackname_suffix") else "",
                request.config.getoption("stackname_suffix"),
            ),
            config_file=cluster_config,
            ssh_key=request.config.getoption("key_path"),
        )
        if not request.config.getoption("cluster"):
            factory.create_cluster(cluster, extra_args=extra_args, raise_on_error=raise_on_error)
        return cluster

    yield _cluster_factory
    if not request.config.getoption("no_delete"):
        factory.destroy_all_clusters(
            keep_logs=request.config.getoption("keep_logs_on_test_failure") and request.node.rep_call.failed
        )


@pytest.fixture(scope="class")
def cluster_model(scheduler):
    return "HIT" if scheduler == "slurm" else "SIT"


def _write_cluster_config_to_outdir(request, cluster_config):
    out_dir = request.config.getoption("output_dir")

    # Sanitize config file name to make it Windows compatible
    # request.node.nodeid example:
    # 'dcv/test_dcv.py::test_dcv_configuration[eu-west-1-c5.xlarge-centos7-sge-8443-0.0.0.0/0-/shared]'
    test_file, test_name = request.node.nodeid.split("::", 1)
    config_file_name = "{0}-{1}".format(test_file, test_name.replace("/", "_"))

    os.makedirs(
        "{out_dir}/clusters_configs/{test_dir}".format(out_dir=out_dir, test_dir=os.path.dirname(test_file)),
        exist_ok=True,
    )
    cluster_config_dst = "{out_dir}/clusters_configs/{config_file_name}.config".format(
        out_dir=out_dir, config_file_name=config_file_name
    )
    copyfile(cluster_config, cluster_config_dst)
    return cluster_config_dst


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
def pcluster_config_reader(test_datadir, vpc_stack, region, request):
    """
    Define a fixture to render pcluster config templates associated to the running test.

    The config for a given test is a pcluster.config.ini file stored in the configs_datadir folder.
    The config can be written by using Jinja2 template engine.
    The current renderer already replaces placeholders for current keys:
        {{ region }}, {{ os }}, {{ instance }}, {{ scheduler}}, {{ key_name }},
        {{ vpc_id }}, {{ public_subnet_id }}, {{ private_subnet_id }}
    The current renderer injects options for custom templates and packages in case these
    are passed to the cli and not present already in the cluster config.
    Also sanity_check is set to true by default unless explicitly set in config.

    :return: a _config_renderer(**kwargs) function which gets as input a dictionary of values to replace in the template
    """

    def _config_renderer(config_file="pcluster.config.ini", **kwargs):
        config_file_path = test_datadir / config_file
        if not os.path.isfile(config_file_path):
            raise FileNotFoundError(f"Cluster config file not found in the expected dir {config_file_path}")
        default_values = _get_default_template_values(vpc_stack, request)
        file_loader = FileSystemLoader(str(test_datadir))
        env = Environment(loader=file_loader)
        rendered_template = env.get_template(config_file).render(**{**kwargs, **default_values})
        config_file_path.write_text(rendered_template)
        add_custom_packages_configs(config_file_path, request, region)
        _enable_sanity_check_if_unset(config_file_path)
        return config_file_path

    return _config_renderer


def add_custom_packages_configs(cluster_config, request, region):
    config = configparser.ConfigParser()
    config.read(cluster_config)
    cluster_template = "cluster {0}".format(config.get("global", "cluster_template", fallback="default"))

    for custom_option in [
        "template_url",
        "hit_template_url",
        "cw_dashboard_template_url",
        "custom_chef_cookbook",
        "custom_ami",
        "pre_install",
        "post_install",
    ]:
        if request.config.getoption(custom_option) and custom_option not in config[cluster_template]:
            config[cluster_template][custom_option] = request.config.getoption(custom_option)
            if custom_option in ["pre_install", "post_install"]:
                _add_policy_for_pre_post_install(cluster_template, config, custom_option, request, region)

    extra_json = json.loads(config.get(cluster_template, "extra_json", fallback="{}"))
    for extra_json_custom_option in ["custom_awsbatchcli_package", "custom_node_package"]:
        if request.config.getoption(extra_json_custom_option):
            cluster = extra_json.get("cluster", {})
            if extra_json_custom_option not in cluster:
                extra_json_custom_option_value = request.config.getoption(extra_json_custom_option)
                # Escape '%' char to avoid 'Invalid Interpolation Syntax' error
                extra_json_custom_option_value = extra_json_custom_option_value.replace("%", "%%")
                cluster[extra_json_custom_option] = extra_json_custom_option_value
                if extra_json_custom_option == "custom_node_package":
                    # Do not skip install recipes so that custom node package can take effect
                    cluster["skip_install_recipes"] = "no"
                extra_json["cluster"] = cluster
    if extra_json:
        config[cluster_template]["extra_json"] = json.dumps(extra_json)

    with cluster_config.open(mode="w") as f:
        config.write(f)


def _add_policy_for_pre_post_install(cluster_template, config, custom_option, request, region):
    match = re.match(r"s3://(.*?)/(.*)", request.config.getoption(custom_option))
    if not match or len(match.groups()) < 2:
        logging.info("{0} script is not an S3 URL".format(custom_option))
    else:
        additional_iam_policies = "arn:" + _get_arn_partition(region) + ":iam::aws:policy/AmazonS3ReadOnlyAccess"
        logging.info(
            "{0} script is an S3 URL, adding additional_iam_policies={1}".format(custom_option, additional_iam_policies)
        )

        if "additional_iam_policies" not in config[cluster_template]:
            config[cluster_template]["additional_iam_policies"] = additional_iam_policies
        else:
            config[cluster_template]["additional_iam_policies"] = (
                config[cluster_template]["additional_iam_policies"] + ", " + additional_iam_policies
            )


def _get_arn_partition(region):
    if region.startswith("us-gov-"):
        return "aws-us-gov"
    elif region.startswith("cn-"):
        return "aws-cn"
    else:
        return "aws"


def _enable_sanity_check_if_unset(cluster_config):
    config = configparser.ConfigParser()
    config.read(cluster_config)

    if "global" not in config:
        config.add_section("global")

    if "sanity_check" not in config["global"]:
        config["global"]["sanity_check"] = "true"

    with cluster_config.open(mode="w") as f:
        config.write(f)


def _get_default_template_values(vpc_stack, request):
    """Build a dictionary of default values to inject in the jinja templated cluster configs."""
    default_values = get_vpc_snakecase_value(vpc_stack)
    default_values.update({dimension: request.node.funcargs.get(dimension) for dimension in DIMENSIONS_MARKER_ARGS})
    default_values["key_name"] = request.config.getoption("key_name")

    return default_values


@pytest.fixture(scope="session")
def cfn_stacks_factory(request):
    """Define a fixture to manage the creation and destruction of CloudFormation stacks."""
    factory = CfnStacksFactory(request.config.getoption("credential"))
    yield factory
    if not request.config.getoption("no_delete"):
        factory.delete_all_stacks()


AVAILABILITY_ZONE_OVERRIDES = {
    # c5.xlarge is not supported in use1-az3
    # FSx Lustre file system creation is currently not supported for use1-az3
    # m6g.xlarge is not supported in use1-az2 or use1-az3
    # p4d.24xlarge is only available on use1-az6
    "us-east-1": ["use1-az6"],
    # m6g.xlarge is not supported in use2-az1
    "us-east-2": ["use2-az2", "use2-az3"],
    # c4.xlarge is not supported in usw2-az4
    # p4d.24xlarge is only available on uw2-az2
    "us-west-2": ["usw2-az2"],
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
    # NAT Gateway not available in sae1-az2
    "sa-east-1": ["sae1-az1", "sae1-az3"],
    # m6g.xlarge instances not available in euw1-az3
    "eu-west-1": ["euw1-az1", "euw1-az2"],
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
def setup_sts_credentials(region, request):
    """Setup environment for the integ tests"""
    set_credentials(region, request.config.getoption("credential"))
    yield
    unset_credentials()


def get_az_id_to_az_name_map(region, credential):
    """Return a dict mapping AZ IDs (e.g, 'use1-az2') to AZ names (e.g., 'us-east-1c')."""
    # credentials are managed manually rather than via setup_sts_credentials because this function
    # is called by a session-scoped fixture, which cannot make use of a class-scoped fixture.
    set_credentials(region, credential)
    try:
        ec2_client = boto3.client("ec2", region_name=region)
        return {
            entry.get("ZoneId"): entry.get("ZoneName")
            for entry in ec2_client.describe_availability_zones().get("AvailabilityZones")
        }
    finally:
        unset_credentials()


def get_availability_zones(region, credential):
    """
    Return a list of availability zones for the given region.

    Note that this function is called by the vpc_stacks fixture. Because vcp_stacks is session-scoped,
    it cannot utilize setup_sts_credentials, which is required in opt-in regions in order to call
    describe_availability_zones.
    """
    set_credentials(region, credential)
    az_list = []
    try:
        client = boto3.client("ec2", region_name=region)
        response_az = client.describe_availability_zones(
            Filters=[
                {"Name": "region-name", "Values": [str(region)]},
                {"Name": "zone-type", "Values": ["availability-zone"]},
            ]
        )
        for az in response_az.get("AvailabilityZones"):
            az_list.append(az.get("ZoneName"))
    finally:
        unset_credentials()
    return az_list


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

        # defining subnets per region to allow AZs override
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
        vpc_config = VPCConfig(
            cidr="192.168.0.0/17",
            additional_cidr_blocks=["192.168.128.0/17"],
            subnets=[public_subnet, private_subnet, private_subnet_different_cidr],
        )
        template = NetworkTemplateBuilder(vpc_configuration=vpc_config, availability_zone=availability_zones[0]).build()
        vpc_stacks[region] = _create_vpc_stack(request, template, region, cfn_stacks_factory)

    return vpc_stacks


@pytest.fixture(scope="class")
def common_pcluster_policies(region):
    """Create four policies to be attached to ec2_iam_role, iam_lamda_role for awsbatch or traditional schedulers."""
    policies = {}
    policies["awsbatch_instance_policy"] = _create_iam_policies(
        "integ-tests-ParallelClusterInstancePolicy-batch-" + random_alphanumeric(), region, "batch_instance_policy.json"
    )
    policies["traditional_instance_policy"] = _create_iam_policies(
        "integ-tests-ParallelClusterInstancePolicy-traditional-" + random_alphanumeric(),
        region,
        "traditional_instance_policy.json",
    )
    policies["awsbatch_lambda_policy"] = _create_iam_policies(
        "integ-tests-ParallelClusterLambdaPolicy-batch-" + random_alphanumeric(),
        region,
        "batch_lambda_function_policy.json",
    )
    policies["traditional_lambda_policy"] = _create_iam_policies(
        "integ-tests-ParallelClusterLambdaPolicy-traditional-" + random_alphanumeric(),
        region,
        "traditional_lambda_function_policy.json",
    )

    yield policies

    iam_client = boto3.client("iam", region_name=region)
    for policy in policies.values():
        iam_client.delete_policy(PolicyArn=policy)


@pytest.fixture(scope="class")
def role_factory(region):
    roles = []
    iam_client = boto3.client("iam", region_name=region)

    def create_role(trusted_service, policies=()):
        iam_role_name = f"integ-tests_{trusted_service}_{region}_{random_alphanumeric()}"
        logging.info(f"Creating iam role {iam_role_name} for {trusted_service}")

        partition = _get_arn_partition(region)
        domain_suffix = ".cn" if partition == "aws-cn" else ""

        trust_relationship_policy_ec2 = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": f"{trusted_service}.amazonaws.com{domain_suffix}"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
        iam_client.create_role(
            RoleName=iam_role_name,
            AssumeRolePolicyDocument=json.dumps(trust_relationship_policy_ec2),
            Description="Role for create custom KMS key",
        )

        logging.info(f"Attaching iam policy to the role {iam_role_name}...")
        for policy in policies:
            iam_client.attach_role_policy(RoleName=iam_role_name, PolicyArn=policy)

        # Having time.sleep here because because it take a while for the the IAM role to become valid for use in the
        # put_key_policy step for creating KMS key, read the following link for reference :
        # https://stackoverflow.com/questions/20156043/how-long-should-i-wait-after-applying-an-aws-iam-policy-before-it-is-valid
        time.sleep(60)
        logging.info(f"Iam role is ready: {iam_role_name}")
        roles.append({"role_name": iam_role_name, "policies": policies})
        return iam_role_name

    yield create_role

    for role in roles:
        role_name = role["role_name"]
        policies = role["policies"]
        for policy in policies:
            iam_client.detach_role_policy(RoleName=role_name, PolicyArn=policy)
        logging.info(f"Deleting iam role {role_name}")
        iam_client.delete_role(RoleName=role_name)


def _create_iam_policies(iam_policy_name, region, policy_filename):
    logging.info("Creating iam policy {0}...".format(iam_policy_name))
    file_loader = FileSystemLoader(pkg_resources.resource_filename(__name__, "/resources"))
    env = Environment(loader=file_loader, trim_blocks=True, lstrip_blocks=True)
    partition = _get_arn_partition(region)
    account_id = (
        boto3.client("sts", region_name=region, endpoint_url=get_sts_endpoint(region))
        .get_caller_identity()
        .get("Account")
    )
    parallel_cluster_instance_policy = env.get_template(policy_filename).render(
        partition=partition,
        region=region,
        account_id=account_id,
        cluster_bucket_name="parallelcluster-*",
    )
    return boto3.client("iam", region_name=region).create_policy(
        PolicyName=iam_policy_name, PolicyDocument=parallel_cluster_instance_policy
    )["Policy"]["Arn"]


@pytest.fixture(scope="class")
def vpc_stack(vpc_stacks, region):
    return vpc_stacks[region]


# If stack creation fails it'll retry once more. This is done to mitigate failures due to resources
# not available in randomly picked AZs.
@retry(
    stop_max_attempt_number=2,
    wait_fixed=5000,
    retry_on_exception=lambda exception: not isinstance(exception, KeyboardInterrupt),
)
def _create_vpc_stack(request, template, region, cfn_stacks_factory):
    try:
        set_credentials(region, request.config.getoption("credential"))
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

    finally:
        unset_credentials()
    return stack


@pytest.fixture(scope="function")
def s3_bucket_factory(region):
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
        logging.info("Deleting S3 bucket {0}".format(bucket[0]))
        try:
            delete_s3_bucket(bucket_name=bucket[0], region=bucket[1])
        except Exception as e:
            logging.error("Failed deleting bucket {0} with exception: {1}".format(bucket[0], e))


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Making test result information available in fixtures"""
    # execute all other hooks to obtain the report object
    outcome = yield
    rep = outcome.get_result()
    # set a report attribute for each phase of a call, which can
    # be "setup", "call", "teardown"
    setattr(item, "rep_" + rep.when, rep)


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
