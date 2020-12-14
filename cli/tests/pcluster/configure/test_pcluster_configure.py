import os
import tempfile
from collections import OrderedDict

import pytest
from assertpy import assert_that
from configparser import ConfigParser

from pcluster.configure.easyconfig import configure
from pcluster.configure.networking import NetworkConfiguration
from tests.pcluster.config.utils import mock_instance_type_info

EASYCONFIG = "pcluster.configure.easyconfig."
NETWORKING = "pcluster.configure.networking."
UTILS = "pcluster.configure.utils."

TEMP_PATH_FOR_CONFIG = os.path.join(tempfile.gettempdir(), "test_pcluster_configure")
PUBLIC_PRIVATE_CONFIGURATION = NetworkConfiguration.PUBLIC_PRIVATE.value.config_type
PUBLIC_CONFIGURATION = NetworkConfiguration.PUBLIC.value.config_type


def _mock_input(mocker, input_in_order):
    mocker.patch(UTILS + "input", side_effect=input_in_order)


def _mock_aws_region(mocker, partition="commercial"):
    regions = {
        "commercial": [
            "eu-north-1",
            "ap-south-1",
            "eu-west-3",
            "eu-west-2",
            "eu-west-1",
            "ap-northeast-2",
            "ap-northeast-1",
            "sa-east-1",
            "ca-central-1",
            "ap-southeast-1",
            "ap-southeast-2",
            "eu-central-1",
            "us-east-1",
            "us-east-2",
            "us-west-1",
            "us-west-2",
        ],
        "china": ["cn-north-1", "cn-northwest-1"],
    }
    mocker.patch(EASYCONFIG + "get_regions", return_value=regions.get(partition))
    if partition == "commercial":
        os.environ["AWS_DEFAULT_REGION"] = "eu-west-1"
    elif partition == "china":
        os.environ["AWS_DEFAULT_REGION"] = "cn-north-1"


def _mock_availability_zone(mocker, availability_zones=("eu-west-1a", "eu-west-1b", "eu-west-1c")):
    # To Do: return different list for different region or instance type
    mocker.patch(EASYCONFIG + "get_supported_az_for_one_instance_type", return_value=availability_zones)


def _mock_cache_availability_zones(mocker):
    mocker.patch(EASYCONFIG + "get_supported_az_for_multi_instance_types")


def _mock_list_keys(mocker, partition="commercial"):
    # If changed look for test_prompt_a_list
    keys = {
        "commercial": ["key1", "key2", "key3", "key4", "key5", "key6"],
        "china": ["some_key1", "some_key2", "some_key3"],
    }
    mocker.patch(EASYCONFIG + "_get_keys", return_value=keys.get(partition))


def _mock_list_vpcs_and_subnets(mocker, empty_region=False, partition="commercial"):
    # If changed look for test_prompt_a_list_of_tuple
    if empty_region:
        mocked_response = {"vpc_list": [], "vpc_to_subnets": {}}
    else:
        response_dict = {
            "commercial": {
                "vpc_list": [
                    OrderedDict(
                        [
                            ("id", "vpc-12345678"),
                            ("name", "ParallelClusterVPC-20190625135738"),
                            ("number_of_subnets", 2),
                        ]
                    ),
                    OrderedDict(
                        [
                            ("id", "vpc-23456789"),
                            ("name", "ParallelClusterVPC-20190624105051"),
                            ("number_of_subnets", 0),
                        ]
                    ),
                    OrderedDict([("id", "vpc-34567891"), ("name", "default"), ("number_of_subnets", 3)]),
                    OrderedDict(
                        [
                            ("id", "vpc-45678912"),
                            ("name", "ParallelClusterVPC-20190626095403"),
                            ("number_of_subnets", 1),
                        ]
                    ),
                ],
                "vpc_subnets": {
                    "vpc-12345678": [
                        OrderedDict(
                            [
                                ("id", "subnet-12345678"),
                                ("name", "ParallelClusterPublicSubnet"),
                                ("size", 256),
                                ("availability_zone", "eu-west-1b"),
                            ]
                        ),
                        OrderedDict(
                            [
                                ("id", "subnet-23456789"),
                                ("name", "ParallelClusterPrivateSubnet"),
                                ("size", 4096),
                                ("availability_zone", "eu-west-1b"),
                            ]
                        ),
                    ],
                    "vpc-23456789": [],
                    "vpc-34567891": [
                        OrderedDict(
                            [
                                ("id", "subnet-34567891"),
                                ("name", None),
                                ("size", 4096),
                                ("availability_zone", "eu-west-1b"),
                            ]
                        ),
                        OrderedDict(
                            [
                                ("id", "subnet-45678912"),
                                ("name", None),
                                ("size", 4096),
                                ("availability_zone", "eu-west-1a"),
                            ]
                        ),
                        OrderedDict(
                            [
                                ("id", "subnet-56789123"),
                                ("name", None),
                                ("size", 4096),
                                ("availability_zone", "eu-west-1c"),
                            ]
                        ),
                    ],
                    "vpc-45678912": [
                        OrderedDict(
                            [
                                ("id", "subnet-45678912"),
                                ("name", "ParallelClusterPublicSubnet"),
                                ("size", 4096),
                                ("availability_zone", "euw1-az4"),
                            ]
                        )
                    ],
                },
            },
            "china": {
                "vpc_list": [
                    OrderedDict(
                        [
                            ("id", "vpc-abcdefgh"),
                            ("name", "ParallelClusterVPC-20190625135738"),
                            ("number_of_subnets", 2),
                        ]
                    ),
                    OrderedDict(
                        [
                            ("id", "vpc-bcdefghi"),
                            ("name", "ParallelClusterVPC-20190624105051"),
                            ("number_of_subnets", 0),
                        ]
                    ),
                    OrderedDict([("id", "vpc-cdefghij"), ("name", "default"), ("number_of_subnets", 3)]),
                    OrderedDict(
                        [
                            ("id", "vpc-abdbabcb"),
                            ("name", "ParallelClusterVPC-20190626095403"),
                            ("number_of_subnets", 1),
                        ]
                    ),
                ],
                "vpc_subnets": {
                    "vpc-abcdefgh": [
                        OrderedDict(
                            [
                                ("id", "subnet-77777777"),
                                ("name", "ParallelClusterPublicSubnet"),
                                ("size", 256),
                                ("availability_zone", "cn-north-1a"),
                            ]
                        ),
                        OrderedDict(
                            [
                                ("id", "subnet-66666666"),
                                ("name", "ParallelClusterPrivateSubnet"),
                                ("size", 4096),
                                ("availability_zone", "cn-north-1a"),
                            ]
                        ),
                    ],
                    "vpc-bcdefghi": [],
                    "vpc-cdefghij": [
                        OrderedDict(
                            [
                                ("id", "subnet-11111111"),
                                ("name", None),
                                ("size", 4096),
                                ("availability_zone", "cn-north-1a"),
                            ]
                        ),
                        OrderedDict(
                            [
                                ("id", "subnet-22222222"),
                                ("name", None),
                                ("size", 4096),
                                ("availability_zone", "cn-north-1a"),
                            ]
                        ),
                        OrderedDict(
                            [
                                ("id", "subnet-33333333"),
                                ("name", None),
                                ("size", 4096),
                                ("availability_zone", "cn-north-1a"),
                            ]
                        ),
                    ],
                    "vpc-abdbabcb": [
                        OrderedDict(
                            [
                                ("id", "subnet-55555555"),
                                ("name", "ParallelClusterPublicSubnet"),
                                ("size", 4096),
                                ("availability_zone", "cn-north-1a"),
                            ]
                        )
                    ],
                },
            },
        }
        mocked_response = response_dict.get(partition)
    mocker.patch(EASYCONFIG + "_get_vpcs_and_subnets", return_value=mocked_response)


def _mock_get_subnets_in_vpc(mocker):
    mocker.patch(NETWORKING + "get_vpc_subnets", return_value=[])


def _mock_vpc_factory(mocker, is_a_valid_vpc):
    vpc_factory = NETWORKING + "VpcFactory"
    mock = mocker.patch(vpc_factory, autospec=True)
    mock.return_value.create.return_value = "vpc-12345678"
    mock.return_value.check.return_value = is_a_valid_vpc


def _mock_ec2_conn(mocker):
    mocker.patch(NETWORKING + "_get_vpc_cidr", return_value="10.0.0.0/16")
    mocker.patch(NETWORKING + "_get_internet_gateway_id", return_value="ig-123")


def _mock_create_network_configuration(mocker, public_subnet_id, private_subnet_id=None):
    def _side_effect_function(config, parameters):
        if private_subnet_id:
            return [
                {"OutputKey": "PrivateSubnetId", "OutputValue": private_subnet_id},
                {"OutputKey": "PublicSubnetId", "OutputValue": public_subnet_id},
            ]
        else:
            return [{"OutputKey": "PublicSubnetId", "OutputValue": public_subnet_id}]

    mocker.patch(NETWORKING + "_create_network_stack", side_effect=_side_effect_function)


def _mock_parallel_cluster_config(mocker):
    supported_instance_types = [
        "t2.nano",
        "t2.micro",
        "t2.large",
        "c5.xlarge",
        "g3.8xlarge",
        "m6g.xlarge",
        "p4d.24xlarge",
    ]
    mocker.patch("pcluster.configure.easyconfig.get_supported_instance_types", return_value=supported_instance_types)
    mocker.patch(
        "pcluster.configure.easyconfig.get_supported_compute_instance_types", return_value=supported_instance_types
    )
    mocker.patch("pcluster.config.cfn_param_types.get_availability_zone_of_subnet", return_value="mocked_avail_zone")
    mocker.patch(
        "pcluster.config.cfn_param_types.get_supported_architectures_for_instance_type",
        side_effect=lambda instance: ["arm64"] if instance == "m6g.xlarge" else ["x86_64"],
    )
    # NOTE: the following shouldn't be needed given that easyconfig doesn't validate the config file,
    #       but it's being included in case that changes in the future.
    mocker.patch(
        "pcluster.config.validators.get_supported_architectures_for_instance_type",
        side_effect=lambda instance: ["arm64"] if instance == "m6g.xlarge" else ["x86_64"],
    )

    for instance_type in supported_instance_types:
        mock_instance_type_info(mocker, instance_type)


def _run_configuration(mocker, path, with_config=False, region=None):
    if not with_config and os.path.isfile(path):
        os.remove(path)
    args = mocker.MagicMock(autospec=True)
    args.config_file = path
    args.region = region
    configure(args)


def _assert_configurations_are_equal(path_config_expected, path_config_after_input):
    assert_that(path_config_expected).exists().is_file()
    assert_that(path_config_after_input).exists().is_file()

    config_expected = ConfigParser()
    config_expected.read(path_config_expected)
    config_expected_dict = {s: dict(config_expected.items(s)) for s in config_expected.sections()}

    config_actual = ConfigParser()
    config_actual.read(path_config_after_input)
    config_actual_dict = {s: dict(config_actual.items(s)) for s in config_actual.sections()}
    assert_that(config_actual_dict).is_equal_to(config_expected_dict)


def _assert_output_error_are_correct(capsys, output, error, config_path):
    readouterr = capsys.readouterr()
    with open(output) as f:
        expected_output = f.read()
        expected_output = expected_output.replace("{{ CONFIG_FILE }}", config_path)
        assert_that(readouterr.out).is_equal_to(expected_output)
    with open(error) as f:
        assert_that(readouterr.err).is_equal_to(f.read())


class ComposeInput:
    def __init__(self, aws_region_name, key, scheduler):
        self.is_not_aws_batch = scheduler != "awsbatch"
        self.input_list = [] if aws_region_name is None else [aws_region_name]
        self.input_list.extend([key, scheduler])

    def add_first_flow(self, op_sys, min_size, max_size, head_node_instance, compute_instance):
        if self.is_not_aws_batch:
            self.input_list.append(op_sys)
        self.input_list.extend([min_size, max_size, head_node_instance])
        if self.is_not_aws_batch:
            self.input_list.append(compute_instance)

    def add_no_automation_no_empty_vpc(self, vpc_id, head_node_id, compute_id):
        self.input_list.extend(["n", vpc_id, "n", head_node_id, compute_id])

    def add_sub_automation(self, vpc_id, network_configuration, vpc_has_subnets=True):
        self.input_list.extend(["n", vpc_id])
        if vpc_has_subnets:
            self.input_list.append("y")
        if self.is_not_aws_batch:
            self.input_list.append(network_configuration)

    def add_vpc_sub_automation_empty_region(self, network_configuration):
        self.input_list.extend(["n", network_configuration])

    def add_vpc_sub_automation(self, network_configuration):
        self.input_list.append("y")
        if self.is_not_aws_batch:
            self.input_list.append(network_configuration)

    def mock_input(self, mocker):
        _mock_input(mocker, self.input_list)


class MockHandler:
    def __init__(self, mocker, empty_region=False, partition="commercial", mock_availability_zone=True):
        self.mocker = mocker
        _mock_aws_region(self.mocker, partition)
        _mock_list_keys(self.mocker, partition)
        _mock_list_vpcs_and_subnets(self.mocker, empty_region, partition)
        _mock_parallel_cluster_config(self.mocker)
        _mock_cache_availability_zones(self.mocker)
        mocker.patch("pcluster.configure.easyconfig.get_default_instance_type", return_value="t2.micro")
        if mock_availability_zone:
            _mock_availability_zone(self.mocker)

    def add_subnet_automation(self, public_subnet_id, is_a_valid_vpc=True, private_subnet_id=None):
        _mock_vpc_factory(self.mocker, is_a_valid_vpc)
        _mock_get_subnets_in_vpc(self.mocker)
        _mock_ec2_conn(self.mocker)
        _mock_create_network_configuration(self.mocker, public_subnet_id, private_subnet_id)


def get_file_path(test_datadir):
    config = test_datadir / "pcluster.config.ini"
    output = test_datadir / "output.txt"
    error = test_datadir / "error.txt"
    #  str for python 2.7 compatibility
    return str(config), str(error), str(output)


def _run_and_assert(mocker, capsys, output, error, expected_config, path_for_config, with_config=False, region=None):
    _run_configuration(mocker, path_for_config, with_config, region)
    _assert_configurations_are_equal(expected_config, path_for_config)
    _assert_output_error_are_correct(capsys, output, error, path_for_config)
    print(output)
    os.remove(path_for_config)


def _run_input_test_with_config(
    mocker,
    config,
    old_config_file,
    error,
    output,
    capsys,
    with_input=False,
    head_node_instance="c5.xlarge",
    compute_instance="g3.8xlarge",
):
    if with_input:
        input_composer = ComposeInput(aws_region_name="us-east-1", key="key2", scheduler="slurm")
        input_composer.add_first_flow(
            op_sys="ubuntu1604",
            min_size="7",
            max_size="18",
            head_node_instance=head_node_instance,
            compute_instance=compute_instance,
        )
        input_composer.add_no_automation_no_empty_vpc(
            vpc_id="vpc-34567891", head_node_id="subnet-34567891", compute_id="subnet-45678912"
        )
    else:
        input_composer = ComposeInput(aws_region_name="", key="", scheduler="")
        input_composer.add_first_flow(op_sys="", min_size="", max_size="", head_node_instance="", compute_instance="")
        input_composer.add_no_automation_no_empty_vpc(vpc_id="", head_node_id="", compute_id="")

    input_composer.mock_input(mocker)

    _run_and_assert(mocker, capsys, output, error, config, old_config_file, with_config=True)


def test_no_automation_no_awsbatch_no_errors(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    MockHandler(mocker)
    input_composer = ComposeInput(aws_region_name="eu-west-1", key="key1", scheduler="torque")
    input_composer.add_first_flow(
        op_sys="alinux", min_size="13", max_size="14", head_node_instance="t2.nano", compute_instance="t2.micro"
    )
    input_composer.add_no_automation_no_empty_vpc(
        vpc_id="vpc-12345678", head_node_id="subnet-12345678", compute_id="subnet-23456789"
    )
    input_composer.mock_input(mocker)

    _run_and_assert(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_no_input_no_automation_no_errors_with_config_file(mocker, capsys, test_datadir):
    """
    Testing easy config with user hitting return on all prompts.

    After running easy config, the old original_config_file should be the same as pcluster.config.ini
    """
    config, error, output = get_file_path(test_datadir)
    old_config_file = str(test_datadir / "original_config_file.ini")

    MockHandler(mocker)

    _run_input_test_with_config(mocker, config, old_config_file, error, output, capsys, with_input=False)


def test_with_region_arg_with_config_file(mocker, capsys, test_datadir):
    """
    Testing easy config with -r/-region provided.

    The region arg should overwrite region specified in config file and environment variable
    """
    config, error, output = get_file_path(test_datadir)

    MockHandler(mocker)

    input_composer = ComposeInput(aws_region_name=None, key="key1", scheduler="torque")
    input_composer.add_first_flow(
        op_sys="alinux", min_size="13", max_size="14", head_node_instance="t2.nano", compute_instance="t2.micro"
    )
    input_composer.add_no_automation_no_empty_vpc(
        vpc_id="vpc-12345678", head_node_id="subnet-12345678", compute_id="subnet-23456789"
    )
    input_composer.mock_input(mocker)
    os.environ["AWS_DEFAULT_REGION"] = "env_region_name_to_be_overwritten"
    _run_and_assert(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG, region="eu-west-1", with_config=True)


def test_region_env_overwrite_region_config(mocker, capsys, test_datadir):
    """Testing environment variable AWS_DEFAULT_REGION overwrites aws_region_name in parallelcluster config file."""
    config, error, output = get_file_path(test_datadir)
    old_config_file = str(test_datadir / "original_config_file.ini")

    MockHandler(mocker)
    os.environ["AWS_DEFAULT_REGION"] = "eu-west-1"

    _run_input_test_with_config(mocker, config, old_config_file, error, output, capsys, with_input=False)


def test_unexisting_instance_type(mocker, capsys, test_datadir):
    """
    Test configuration file with wrong values that must be overridden by user inputs.

    This test verifies that the validation steps are not performed with initial or default values
    (e.g. t2.micro as instance type in a region that doesn't support it).
    """
    config, error, output = get_file_path(test_datadir)
    old_config_file = str(test_datadir / "original_config_file.ini")

    MockHandler(mocker)

    _run_input_test_with_config(
        mocker,
        config,
        old_config_file,
        error,
        output,
        capsys,
        with_input=True,
        head_node_instance="m6g.xlarge",
        compute_instance="m6g.xlarge",
    )


def test_no_available_no_input_no_automation_no_errors_with_config_file(mocker, capsys, test_datadir):
    """
    Testing easy config with user hitting return on all prompts.

    Mocking the case where parameters: aws_region_name, key_name, vpc_id, compute_subnet_id, head_node_subnet_id.
    Are not found in available list under new partition/region/vpc configuration.
    After running easy config, the old original_config_file should be the same as pcluster.config.ini
    """
    config, error, output = get_file_path(test_datadir)
    old_config_file = str(test_datadir / "original_config_file.ini")

    MockHandler(mocker, partition="china")
    _mock_availability_zone(mocker, ["cn-north-1a"])

    _run_input_test_with_config(mocker, config, old_config_file, error, output, capsys, with_input=False)


def test_with_input_no_automation_no_errors_with_config_file(mocker, capsys, test_datadir):
    """
    Testing only inputting queue_size inputs.

    After running easy config on the old original_config_file, output should be the same as pcluster.config.ini
    """
    config, error, output = get_file_path(test_datadir)
    old_config_file = str(test_datadir / "original_config_file.ini")

    MockHandler(mocker)

    _run_input_test_with_config(
        mocker,
        config,
        old_config_file,
        error,
        output,
        capsys,
        with_input=True,
        head_node_instance="m6g.xlarge",
        compute_instance="m6g.xlarge",
    )


def test_no_automation_yes_awsbatch_no_errors(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    MockHandler(mocker)

    input_composer = ComposeInput(aws_region_name="eu-west-1", key="key1", scheduler="awsbatch")
    input_composer.add_first_flow(
        op_sys=None, min_size="13", max_size="14", head_node_instance="t2.nano", compute_instance=None
    )
    input_composer.add_no_automation_no_empty_vpc(
        vpc_id="vpc-12345678", head_node_id="subnet-12345678", compute_id="subnet-23456789"
    )
    input_composer.mock_input(mocker)

    _run_and_assert(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_subnet_automation_no_awsbatch_no_errors_empty_vpc(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789")

    input_composer = ComposeInput(aws_region_name="eu-west-1", key="key1", scheduler="sge")
    input_composer.add_first_flow(
        op_sys="centos7", min_size="13", max_size="14", head_node_instance="t2.nano", compute_instance="t2.micro"
    )
    input_composer.add_sub_automation(
        vpc_id="vpc-23456789", network_configuration=PUBLIC_PRIVATE_CONFIGURATION, vpc_has_subnets=False
    )
    input_composer.mock_input(mocker)

    _run_and_assert(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_subnet_automation_no_awsbatch_no_errors(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789")

    input_composer = ComposeInput(aws_region_name="eu-west-1", key="key1", scheduler="sge")
    input_composer.add_first_flow(
        op_sys="centos7", min_size="13", max_size="14", head_node_instance="t2.nano", compute_instance="t2.micro"
    )
    input_composer.add_sub_automation(
        vpc_id="vpc-12345678", network_configuration=PUBLIC_PRIVATE_CONFIGURATION, vpc_has_subnets=True
    )
    input_composer.mock_input(mocker)

    _run_and_assert(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_subnet_automation_no_awsbatch_no_errors_with_config_file(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)
    old_config_file = str(test_datadir / "original_config_file.ini")

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789")

    input_composer = ComposeInput(aws_region_name="eu-west-1", key="key1", scheduler="sge")
    input_composer.add_first_flow(
        op_sys="centos7", min_size="13", max_size="14", head_node_instance="t2.nano", compute_instance="t2.micro"
    )
    input_composer.add_sub_automation(
        vpc_id="vpc-12345678", network_configuration=PUBLIC_PRIVATE_CONFIGURATION, vpc_has_subnets=True
    )
    input_composer.mock_input(mocker)

    _run_and_assert(mocker, capsys, output, error, config, old_config_file, with_config=True)


def test_vpc_automation_no_awsbatch_no_errors(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789")

    input_composer = ComposeInput(aws_region_name="eu-west-1", key="key1", scheduler="sge")
    input_composer.add_first_flow(
        op_sys="centos7", min_size="13", max_size="14", head_node_instance="t2.nano", compute_instance="t2.micro"
    )
    input_composer.add_vpc_sub_automation(network_configuration=PUBLIC_PRIVATE_CONFIGURATION)
    input_composer.mock_input(mocker)

    _run_and_assert(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_vpc_automation_yes_awsbatch_no_errors(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789")

    input_composer = ComposeInput(aws_region_name="eu-west-1", key="key1", scheduler="awsbatch")
    input_composer.add_first_flow(
        op_sys=None, min_size="13", max_size="14", head_node_instance="t2.nano", compute_instance=None
    )
    input_composer.add_vpc_sub_automation(network_configuration=PUBLIC_PRIVATE_CONFIGURATION)
    input_composer.mock_input(mocker)

    _run_and_assert(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_vpc_automation_invalid_vpc_block(mocker, capsys, test_datadir):
    with pytest.raises(SystemExit):
        config, error, output = get_file_path(test_datadir)

        mock_handler = MockHandler(mocker)
        mock_handler.add_subnet_automation(
            public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789", is_a_valid_vpc=False
        )

        input_composer = ComposeInput(aws_region_name="eu-west-1", key="key1", scheduler="awsbatch")
        input_composer.add_first_flow(
            op_sys=None, min_size="13", max_size="14", head_node_instance="t2.nano", compute_instance=None
        )
        input_composer.add_vpc_sub_automation(network_configuration=PUBLIC_PRIVATE_CONFIGURATION)
        input_composer.mock_input(mocker)
        _run_and_assert(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_subnet_automation_yes_awsbatch_invalid_vpc(mocker, capsys, test_datadir, caplog):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(
        public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789", is_a_valid_vpc=False
    )

    input_composer = ComposeInput(aws_region_name="eu-west-1", key="key1", scheduler="awsbatch")
    input_composer.add_first_flow(
        op_sys=None, min_size="13", max_size="14", head_node_instance="t2.nano", compute_instance=None
    )
    input_composer.add_sub_automation(vpc_id="vpc-12345678", network_configuration=PUBLIC_PRIVATE_CONFIGURATION)
    input_composer.mock_input(mocker)
    _run_and_assert(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)
    assert_that("WARNING: The VPC does not have the correct parameters set." in caplog.text).is_true()


def test_vpc_automation_no_vpc_in_region(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker, empty_region=True)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789")

    input_composer = ComposeInput(aws_region_name="eu-west-1", key="key1", scheduler="slurm")
    input_composer.add_first_flow(
        op_sys="centos7", min_size="13", max_size="14", head_node_instance="t2.nano", compute_instance="t2.micro"
    )
    input_composer.add_vpc_sub_automation_empty_region(network_configuration=PUBLIC_PRIVATE_CONFIGURATION)
    input_composer.mock_input(mocker)

    _run_and_assert(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_vpc_automation_no_vpc_in_region_public(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker, empty_region=True)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678")

    input_composer = ComposeInput(aws_region_name="eu-west-1", key="key1", scheduler="slurm")
    input_composer.add_first_flow(
        op_sys="centos7", min_size="13", max_size="14", head_node_instance="t2.nano", compute_instance="t2.micro"
    )
    input_composer.add_vpc_sub_automation_empty_region(network_configuration="2")
    input_composer.mock_input(mocker)

    _run_and_assert(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_filtered_subnets_by_az(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)
    old_config_file = str(test_datadir / "original_config_file.ini")

    MockHandler(mocker, mock_availability_zone=False)
    _mock_availability_zone(mocker, ["eu-west-1a"])

    _run_input_test_with_config(mocker, config, old_config_file, error, output, capsys, with_input=False)


def test_bad_config_file(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)
    old_config_file = str(test_datadir / "original_config_file.ini")

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789")

    input_composer = ComposeInput(aws_region_name="eu-west-1", key="key1", scheduler="sge")
    input_composer.add_first_flow(
        op_sys="centos7", min_size="13", max_size="14", head_node_instance="t2.nano", compute_instance="t2.micro"
    )
    input_composer.add_sub_automation(
        vpc_id="vpc-12345678", network_configuration=PUBLIC_PRIVATE_CONFIGURATION, vpc_has_subnets=True
    )
    input_composer.mock_input(mocker)

    _run_and_assert(mocker, capsys, output, error, config, old_config_file, with_config=True)


def general_wrapper_for_prompt_testing(
    mocker,
    region="eu-west-1",
    scheduler="torque",
    op_sys="centos7",
    min_size="0",
    max_size="10",
    head_node_instance="t2.nano",
    compute_instance="t2.micro",
    key="key1",
    vpc_id="vpc-12345678",
    head_node_id="subnet-12345678",
    compute_id="subnet-23456789",
):
    path = os.path.join(tempfile.gettempdir(), "test_pcluster_configure")
    MockHandler(mocker)
    input_composer = ComposeInput(aws_region_name=region, key=key, scheduler=scheduler)
    input_composer.add_first_flow(op_sys, min_size, max_size, head_node_instance, compute_instance)
    input_composer.add_no_automation_no_empty_vpc(vpc_id, head_node_id, compute_id)
    input_composer.mock_input(mocker)

    _run_configuration(mocker, path)
    return True


def test_vpc_automation_with_no_single_qualified_az(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker, mock_availability_zone=False)
    mocker.patch(
        EASYCONFIG + "get_supported_az_for_one_instance_type",
        new=lambda x: ["eu-west-1a"] if x == "t2.nano" else ["eu-west-1b"],
    )
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789")

    input_composer = ComposeInput(aws_region_name="eu-west-1", key="key1", scheduler="sge")
    input_composer.add_first_flow(
        op_sys="centos7", min_size="13", max_size="14", head_node_instance="t2.nano", compute_instance="t2.micro"
    )
    input_composer.add_vpc_sub_automation(network_configuration=PUBLIC_PRIVATE_CONFIGURATION)
    input_composer.mock_input(mocker)
    path = os.path.join(tempfile.gettempdir(), "test_pcluster_configure")
    with pytest.raises(SystemExit):
        _run_configuration(mocker, path)


@pytest.mark.parametrize(
    "min_size, max_size",
    [
        ("17", "16"),
        ("-17", "16"),
        ("1", "-16"),
        ("1", "1.6"),
        ("17", "1,6"),
        ("schrodinger", "16"),
        ("12", "cat"),
        ("2500", ""),
    ],
)
def test_invalid_min_max_exception(mocker, min_size, max_size):
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, min_size=min_size, max_size=max_size)


@pytest.mark.parametrize("min_size, max_size", [("", ""), ("1", "2"), ("", "1"), ("4", "")])
def test_valid_min_max(mocker, min_size, max_size):

    assert_that(general_wrapper_for_prompt_testing(mocker, min_size=min_size, max_size=max_size)).is_true()


@pytest.mark.parametrize("key", ["key0", "key7", "0", "-1", "-17", "8", "sopralapancalacapracampa"])
def test_invalid_key_exception(mocker, key):
    # Remember that keys go from key1...key6
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, key=key)


def test_valid_key(mocker):
    for i in range(1, 7):

        assert_that(general_wrapper_for_prompt_testing(mocker, key="key" + str(i))).is_true()

        assert_that(general_wrapper_for_prompt_testing(mocker, key=str(i))).is_true()


@pytest.mark.parametrize(
    "vpc_id",
    [
        "2 subnets inside",
        "ParallelClusterVPC-20190625135738",
        "vpc-0",
        "vpc-7",
        "0",
        "-1",
        "-17",
        "8",
        "sopralapancalacapracampa",
    ],
)
def test_invalid_vpc(mocker, vpc_id):
    # Look at _mock_list_vpcs and subnets
    with pytest.raises(StopIteration):

        general_wrapper_for_prompt_testing(mocker, vpc_id=vpc_id)


@pytest.mark.parametrize(
    "vpc_id, head_node_id, compute_id",
    [
        ("vpc-12345678", "subnet-34567891", "subnet-45678912"),
        ("vpc-23456789", "subnet-34567891", "subnet-45678912"),
        ("vpc-34567891", "subnet-12345678", "subnet-23456789"),
    ],
)
def test_invalid_subnet(mocker, vpc_id, head_node_id, compute_id):
    with pytest.raises(StopIteration):

        assert_that(
            general_wrapper_for_prompt_testing(mocker, vpc_id=vpc_id, head_node_id=head_node_id, compute_id=compute_id)
        ).is_true()


@pytest.mark.parametrize(
    "vpc_id, head_node_id, compute_id",
    [("vpc-12345678", "subnet-12345678", "subnet-23456789"), ("vpc-34567891", "subnet-45678912", "subnet-45678912")],
)
def test_valid_subnet(mocker, vpc_id, head_node_id, compute_id):
    # valid subnets

    assert_that(
        general_wrapper_for_prompt_testing(mocker, vpc_id=vpc_id, head_node_id=head_node_id, compute_id=compute_id)
    ).is_true()


def test_hit_config_file(mocker, capsys, test_datadir):
    old_config_file = str(test_datadir / "original_config_file.ini")

    MockHandler(mocker)

    # Expected sys exit with error
    with pytest.raises(SystemExit, match="ERROR: Configuration in file .* cannot be overwritten"):
        _run_configuration(mocker, old_config_file, with_config=True)
