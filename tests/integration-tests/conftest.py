import logging
from shutil import copyfile

import pytest

from clusters_factory import ClustersFactory
from conftest_markers import (
    DIMENSIONS_MARKER_ARGS,
    add_default_markers,
    check_marker_dimensions,
    check_marker_list,
    check_marker_skip_dimensions,
    check_marker_skip_list,
)
from jinja2 import Environment, FileSystemLoader


def pytest_addoption(parser):
    """Register argparse-style options and ini-style config values, called once at the beginning of a test run."""
    parser.addoption("--regions", help="aws region where tests are executed", default=["us-east-1"], nargs="+")
    parser.addoption("--instances", help="aws instances under test", default=["c5.xlarge"], nargs="+")
    parser.addoption("--oss", help="OSs under test", default=["alinux"], nargs="+")
    parser.addoption("--schedulers", help="schedulers under test", default=["slurm"], nargs="+")
    parser.addoption("--tests-log-file", help="file used to write test logs", default="pytest.log")
    parser.addoption("--custom-node-url", help="url to a custom node package")
    parser.addoption("--custom-cookbook-url", help="url to a custom cookbook package")
    parser.addoption("--custom-template-url", help="url to a custom cfn template")
    parser.addoption("--output-dir", help="output dir for tests artifacts")


def pytest_generate_tests(metafunc):
    """Generate (multiple) parametrized calls to a test function."""
    _parametrize_from_option(metafunc, "instance", "instances")
    _parametrize_from_option(metafunc, "region", "regions")
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
    add_default_markers(item)

    check_marker_list(item, "instances", "instance")
    check_marker_list(item, "regions", "region")
    check_marker_list(item, "oss", "os")
    check_marker_list(item, "schedulers", "scheduler")
    check_marker_skip_list(item, "skip_instances", "instance")
    check_marker_skip_list(item, "skip_regions", "region")
    check_marker_skip_list(item, "skip_oss", "os")
    check_marker_skip_list(item, "skip_schedulers", "scheduler")
    check_marker_dimensions(item)
    check_marker_skip_dimensions(item)

    logging.info("Running test " + item.name)


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
        if value:
            item.user_properties.append((dimension, value))


@pytest.fixture(scope="class")
def clusters_factory(request):
    """
    Define a fixture to manage the creation and destruction of clusters.

    The configs used to create clusters are dumped to output_dir/clusters_configs/{test_name}.config
    """
    factory = ClustersFactory(test_name=request.node.name)

    def _cluster_factory(cluster_config):
        cluster_config_dst = "{out_dir}/clusters_configs/{test_name}.config".format(
            out_dir=request.config.getoption("output_dir"), test_name=request.node.nodeid
        )
        copyfile(cluster_config, cluster_config_dst)
        return factory.create_cluster(cluster_config_dst)

    yield _cluster_factory
    factory.destroy_all_clusters()


@pytest.fixture()
def configs_datadir(request, datadir):
    """
    Inject the config_datadir where cluster configs for the specific test function are stored.

    If the test function is declared in a class then datadir is ClassName/FunctionName
    otherwise it is only FunctionName.
    """
    function_name = request.function.__name__
    if not request.cls:
        return datadir / function_name

    class_name = request.cls.__name__
    return datadir / "{0}/{1}".format(class_name, function_name)


@pytest.fixture()
def pcluster_config_reader(configs_datadir, request):
    """
    Define a fixture to render pcluster config templates associated to the running test.

    The config for a given test is a pcluster.config.ini file stored in the configs_datadir folder.
    The config can be written by using Jinja2 template engine.
    The current renderer already replaces placeholders for the common test dimensions (region, instance, os, scheduler)
    by reading them from the test input parameters.

    :return: a _config_renderer(**kwargs) function which gets as input a dictionary of values to replace in the template
    """
    config_file = "pcluster.config.ini"

    def _config_renderer(**kwargs):
        dimensions_values = {dimension: request.node.funcargs.get(dimension) for dimension in DIMENSIONS_MARKER_ARGS}
        file_loader = FileSystemLoader(str(configs_datadir))
        env = Environment(loader=file_loader)
        rendered_template = env.get_template(config_file).render(**{**kwargs, **dimensions_values})
        (configs_datadir / config_file).write_text(rendered_template)
        return configs_datadir / config_file

    return _config_renderer
