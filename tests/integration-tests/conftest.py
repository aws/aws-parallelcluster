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
from shutil import copyfile
from traceback import format_tb

import configparser
import pytest
from retrying import retry

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
from jinja2 import Environment, FileSystemLoader
from network_template_builder import Gateways, NetworkTemplateBuilder, SubnetConfig, VPCConfig
from utils import (
    create_s3_bucket,
    delete_s3_bucket,
    get_architecture_supported_by_instance_type,
    get_vpc_snakecase_value,
    random_alphanumeric,
    set_credentials,
    set_logger_formatter,
    unset_credentials,
)


def pytest_addoption(parser):
    """Register argparse-style options and ini-style config values, called once at the beginning of a test run."""
    parser.addoption("--regions", help="aws region where tests are executed", default=["us-east-1"], nargs="+")
    parser.addoption(
        "--credential", help="STS credential endpoint, in the format <region>,<endpoint>,<ARN>,<externalId>.", nargs="+"
    )
    parser.addoption("--instances", help="aws instances under test", default=["c5.xlarge"], nargs="+")
    parser.addoption("--oss", help="OSs under test", default=["alinux"], nargs="+")
    parser.addoption("--schedulers", help="schedulers under test", default=["slurm"], nargs="+")
    parser.addoption("--tests-log-file", help="file used to write test logs", default="pytest.log")
    parser.addoption("--output-dir", help="output dir for tests artifacts")
    # Can't mark fields as required due to: https://github.com/pytest-dev/pytest/issues/2026
    parser.addoption("--key-name", help="key to use for EC2 instances", type=str)
    parser.addoption("--key-path", help="key path to use for SSH connections", type=str)
    parser.addoption("--custom-chef-cookbook", help="url to a custom cookbook package")
    parser.addoption(
        "--createami-custom-chef-cookbook", help="url to a custom cookbook package for the createami command"
    )
    parser.addoption("--custom-awsbatch-template-url", help="url to a custom awsbatch template")
    parser.addoption("--template-url", help="url to a custom cfn template")
    parser.addoption("--custom-awsbatchcli-package", help="url to a custom awsbatch cli package")
    parser.addoption("--custom-node-package", help="url to a custom node package")
    parser.addoption("--custom-ami", help="custom AMI to use in the tests")
    parser.addoption("--vpc-stack", help="Name of an existing vpc stack.")
    parser.addoption("--cluster", help="Use an existing cluster instead of creating one.")
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
    _parametrize_from_option(metafunc, "region", "regions")
    _parametrize_from_option(metafunc, "instance", "instances")
    _parametrize_from_option(metafunc, "os", "oss")
    _parametrize_from_option(metafunc, "scheduler", "schedulers")


def pytest_configure(config):
    """This hook is called for every plugin and initial conftest file after command line options have been parsed."""
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


def pytest_collection_modifyitems(config, items):
    """Called after collection has been performed, may filter or re-order the items in-place."""
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

    _add_filename_markers(items)


def pytest_collection_finish(session):
    _log_collected_tests(session.config, session.items)


def _log_collected_tests(config, items):
    logging.info("Collected test=%d", len(items))
    out_dir = config.getoption("output_dir")
    with open(f"{out_dir}/collected_tests.txt", "a") as out_f:
        out_f.write("\n".join(map(lambda item: item.nodeid, items)))


def pytest_exception_interact(node, call, report):
    """Called when an exception was raised which can potentially be interactively handled.."""
    logging.error(
        "Exception raised while executing %s: %s\n%s",
        node.name,
        call.excinfo.value,
        "".join(format_tb(call.excinfo.tb)),
    )


def _add_filename_markers(items):
    """Add a marker based on the name of the file where the test case is defined."""
    for item in items:
        test_location = os.path.splitext(os.path.basename(item.location[0]))[0]
        marker = re.sub(r"test_|_test", "", test_location)
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
    for dimension in DIMENSIONS_MARKER_ARGS:
        value = item.funcargs.get(dimension)
        if value and (dimension, value) not in item.user_properties:
            item.user_properties.append((dimension, value))


@pytest.fixture(scope="class")
@pytest.mark.usefixtures("setup_sts_credentials")
def clusters_factory(request):
    """
    Define a fixture to manage the creation and destruction of clusters.

    The configs used to create clusters are dumped to output_dir/clusters_configs/{test_name}.config
    """
    factory = ClustersFactory(keep_logs_on_failure=request.config.getoption("keep_logs_on_cluster_failure"))

    def _cluster_factory(cluster_config):
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
            factory.create_cluster(cluster)
        return cluster

    yield _cluster_factory
    if not request.config.getoption("no_delete"):
        factory.destroy_all_clusters(
            keep_logs=request.config.getoption("keep_logs_on_test_failure") and request.node.rep_call.failed
        )


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
def pcluster_config_reader(test_datadir, vpc_stacks, region, request):
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
        default_values = _get_default_template_values(vpc_stacks, region, request)
        file_loader = FileSystemLoader(str(test_datadir))
        env = Environment(loader=file_loader)
        rendered_template = env.get_template(config_file).render(**{**kwargs, **default_values})
        config_file_path.write_text(rendered_template)
        _add_custom_packages_configs(config_file_path, request)
        _enable_sanity_check_if_unset(config_file_path)
        return config_file_path

    return _config_renderer


def _add_custom_packages_configs(cluster_config, request):
    config = configparser.ConfigParser()
    config.read(cluster_config)
    cluster_template = "cluster {0}".format(config.get("global", "cluster_template", fallback="default"))

    for custom_option in ["template_url", "custom_awsbatch_template_url", "custom_chef_cookbook", "custom_ami"]:
        if request.config.getoption(custom_option) and custom_option not in config[cluster_template]:
            config[cluster_template][custom_option] = request.config.getoption(custom_option)

    extra_json = json.loads(config.get(cluster_template, "extra_json", fallback="{}"))
    for extra_json_custom_option in ["custom_awsbatchcli_package", "custom_node_package"]:
        if request.config.getoption(extra_json_custom_option):
            cluster = extra_json.get("cluster", {})
            if extra_json_custom_option not in cluster:
                cluster[extra_json_custom_option] = request.config.getoption(extra_json_custom_option)
                if extra_json_custom_option == "custom_node_package":
                    # Do not skip install recipes so that custom node package can take effect
                    cluster["skip_install_recipes"] = "no"
                extra_json["cluster"] = cluster
    if extra_json:
        config[cluster_template]["extra_json"] = json.dumps(extra_json)

    with cluster_config.open(mode="w") as f:
        config.write(f)


def _enable_sanity_check_if_unset(cluster_config):
    config = configparser.ConfigParser()
    config.read(cluster_config)

    if "global" not in config:
        config.add_section("global")

    if "sanity_check" not in config["global"]:
        config["global"]["sanity_check"] = "true"

    with cluster_config.open(mode="w") as f:
        config.write(f)


def _get_default_template_values(vpc_stacks, region, request):
    """Build a dictionary of default values to inject in the jinja templated cluster configs."""
    default_values = get_vpc_snakecase_value(region, vpc_stacks)
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


# FIXME: we need to find a better solution to this since AZs are independently mapped to names for each AWS account.
# https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-regions-availability-zones.html
AVAILABILITY_ZONE_OVERRIDES = {
    # c5.xlarge is not supported in us-east-1e
    # FSx Lustre file system creation is currently not supported for us-east-1e
    # "us-east-1": ["us-east-1a", "us-east-1b", "us-east-1c", "us-east-1d", "us-east-1f"],
    "us-east-1": ["us-east-1a", "us-east-1b"],
    # c4.xlarge is not supported in us-west-2d
    "us-west-2": ["us-west-2a", "us-west-2b", "us-west-2c"],
    # c5.xlarge is not supported in ap-southeast-2a
    "ap-southeast-2": ["ap-southeast-2b", "ap-southeast-2c"],
    # c4.xlarge is not supported in ap-northeast-2b
    "ap-northeast-2": ["ap-northeast-2a", "ap-northeast-2c"],
    # c5.xlarge is not supported in ap-southeast-1c
    "ap-southeast-1": ["ap-southeast-1a", "ap-southeast-1b"],
    # c4.xlarge is not supported in ap-south-1c
    "ap-south-1": ["ap-south-1a", "ap-south-1b"],
    # NAT Gateway not available in sa-east-1b
    "sa-east-1": ["sa-east-1a", "sa-east-1c"],
}


@pytest.fixture(scope="class", autouse=True)
def setup_sts_credentials(region, request):
    """Setup environment for the integ tests"""
    set_credentials(region, request.config.getoption("credential"))
    yield
    unset_credentials()


@pytest.fixture(scope="session", autouse=True)
def vpc_stacks(cfn_stacks_factory, request):
    """Create VPC used by integ tests in all configured regions."""
    regions = request.config.getoption("regions")
    vpc_stacks = {}
    for region in regions:
        # Randomly select 2 AZs from list WITHOUT replacement, hence the need for [None, None].
        # Creating private_subnet_different_cidr in a different AZ for test_efs
        # To-do: isolate this logic and create a compute subnet in different AZ than master in test_efs
        availability_zones = random.sample(AVAILABILITY_ZONE_OVERRIDES.get(region, [None, None]), k=2)
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
            name="integ-tests-vpc-{0}{1}{2}".format(
                random_alphanumeric(),
                "-" if request.config.getoption("stackname_suffix") else "",
                request.config.getoption("stackname_suffix"),
            ),
            region=region,
            template=template.to_json(),
        )
        cfn_stacks_factory.create_stack(stack)
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
