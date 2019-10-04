import os
import tempfile

import pytest
from configparser import ConfigParser

from assertpy import assert_that
from pcluster.config.pcluster_config import PclusterConfig
from pcluster.configure.easyconfig import configure
from pcluster.configure.networking import NetworkConfiguration

EASYCONFIG = "pcluster.configure.easyconfig."
NETWORKING = "pcluster.configure.networking."
UTILS = "pcluster.configure.utils."

TEMP_PATH_FOR_CONFIG = os.path.join(tempfile.gettempdir(), "test_pcluster_configure")
PUBLIC_PRIVATE_CONFIGURATION = NetworkConfiguration.PUBLIC_PRIVATE.value.config_type
PUBLIC_CONFIGURATION = NetworkConfiguration.PUBLIC.value.config_type


def _mock_input(mocker, input_in_order):
    mocker.patch(UTILS + "input", side_effect=input_in_order)


def _mock_aws_region(mocker):
    regions = [
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
    ]
    mocker.patch(EASYCONFIG + "get_regions", return_value=regions)


def _mock_list_keys(mocker):
    # If changed look for test_prompt_a_list
    keys = ["key1", "key2", "key3", "key4", "key5", "key6"]
    mocker.patch(EASYCONFIG + "_get_keys", return_value=keys)


def _mock_list_vpcs_and_subnets(mocker, empty_region=False):
    # If changed look for test_prompt_a_list_of_tuple
    if empty_region:
        mocked_response = {"vpc_list": [], "vpc_to_subnets": {}}
    else:
        mocked_response = {
            "vpc_list": [
                ("vpc-12345678", "ParallelClusterVPC-20190625135738", "2 subnets inside"),
                ("vpc-23456789", "ParallelClusterVPC-20190624105051", "0 subnets inside"),
                ("vpc-34567891", "default", "3 subnets inside"),
                ("vpc-45678912", "ParallelClusterVPC-20190626095403", "1 subnets inside"),
            ],
            "vpc_subnets": {
                "vpc-12345678": [
                    ("subnet-12345678", "ParallelClusterPublicSubnet", "Subnet size: 256"),
                    ("subnet-23456789", "ParallelClusterPrivateSubnet", "Subnet size: 4096"),
                ],
                "vpc-23456789": [],
                "vpc-34567891": [
                    ("subnet-34567891", "Subnet size: 4096"),
                    ("subnet-45678912", "Subnet size: 4096"),
                    ("subnet-56789123", "Subnet size: 4096"),
                ],
                "vpc-45678912": [("subnet-45678912", "ParallelClusterPublicSubnet", "Subnet size: 4096")],
            },
        }
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
    mocker.patch("pcluster.config.param_types.get_avail_zone", return_value="mocked_avail_zone")
    mocker.patch.object(PclusterConfig, "_PclusterConfig__validate")


def _launch_config(mocker, path, remove_path=True):
    if remove_path and os.path.isfile(path):
        os.remove(path)
    args = mocker.MagicMock(autospec=True)
    args.config_file = path
    configure(args)


def _are_configurations_equals(path_verify, path_verified):
    if not os.path.isfile(path_verify):
        return False
    if not os.path.isfile(path_verified):
        return False
    config_temp = ConfigParser()
    config_temp.read(path_verify)
    dict1 = {s: dict(config_temp.items(s)) for s in config_temp.sections()}
    config_expected = ConfigParser()
    config_expected.read(path_verified)
    dict2 = {s: dict(config_expected.items(s)) for s in config_expected.sections()}
    for section_name, section in dict1.items():
        for key, value in section.items():
            try:
                if dict2[section_name][key] != value:
                    print(
                        "\nTest failed: Parameter '{0}' in section '{1}' is different from the expected one.".format(
                            key, section_name
                        )
                    )
                    print("The value is '{0}' but it should be '{1}'".format(value, dict2[section_name][key]))
                    return False
            except KeyError:
                print("\nTest failed: Parameter '{0}' doesn't exist in section '{1}'.".format(key, section_name))
                return False
    return True


def _are_output_error_correct(capsys, output, error, config_path):
    readouterr = capsys.readouterr()
    with open(output) as f:
        expected_output = f.read()
        expected_output = expected_output.replace("{{ CONFIG_FILE }}", config_path)
        assert_that(readouterr.out).is_equal_to(expected_output)
    with open(error) as f:
        assert_that(readouterr.err).is_equal_to(f.read())


class ComposeInput:
    def __init__(self, aws_region_name, scheduler):
        self.is_not_aws_batch = scheduler != "awsbatch"
        self.input_list = [aws_region_name, scheduler]

    def add_first_flow(self, op_sys, min_size, max_size, master_instance, compute_instance, key):
        if self.is_not_aws_batch:
            self.input_list.append(op_sys)
        self.input_list.extend([min_size, max_size, master_instance])
        if self.is_not_aws_batch:
            self.input_list.append(compute_instance)
        self.input_list.append(key)

    def add_no_automation_no_empty_vpc(self, vpc_id, master_id, compute_id):
        self.input_list.extend(["n", vpc_id, "n", master_id, compute_id])

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

    def finalize_config(self, mocker):
        _mock_input(mocker, self.input_list)


class MockHandler:
    def __init__(self, mocker, empty_region=False):
        self.mocker = mocker
        _mock_aws_region(self.mocker)
        _mock_list_keys(self.mocker)
        _mock_list_vpcs_and_subnets(self.mocker, empty_region)
        _mock_parallel_cluster_config(self.mocker)

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


def _verify_test(mocker, capsys, output, error, config, temp_path_for_config):
    _launch_config(mocker, temp_path_for_config)
    assert_that(_are_configurations_equals(temp_path_for_config, config)).is_true()
    _are_output_error_correct(capsys, output, error, temp_path_for_config)
    os.remove(temp_path_for_config)


def test_no_automation_no_awsbatch_no_errors(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    MockHandler(mocker)
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="torque")
    input_composer.add_first_flow(
        op_sys="alinux",
        min_size="13",
        max_size="14",
        master_instance="t2.nano",
        compute_instance="t2.micro",
        key="key1",
    )
    input_composer.add_no_automation_no_empty_vpc(
        vpc_id="vpc-12345678", master_id="subnet-12345678", compute_id="subnet-23456789"
    )
    input_composer.finalize_config(mocker)

    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_no_automation_yes_awsbatch_no_errors(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    MockHandler(mocker)
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="awsbatch")
    input_composer.add_first_flow(
        op_sys=None, min_size="13", max_size="14", master_instance="t2.nano", compute_instance=None, key="key1"
    )
    input_composer.add_no_automation_no_empty_vpc(
        vpc_id="vpc-12345678", master_id="subnet-12345678", compute_id="subnet-23456789"
    )
    input_composer.finalize_config(mocker)

    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_subnet_automation_no_awsbatch_no_errors_empty_vpc(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789")
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="sge")
    input_composer.add_first_flow(
        op_sys="centos6",
        min_size="13",
        max_size="14",
        master_instance="t2.nano",
        compute_instance="t2.micro",
        key="key1",
    )
    input_composer.add_sub_automation(
        vpc_id="vpc-23456789", network_configuration=PUBLIC_PRIVATE_CONFIGURATION, vpc_has_subnets=False
    )
    input_composer.finalize_config(mocker)

    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_subnet_automation_no_awsbatch_no_errors(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789")
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="sge")
    input_composer.add_first_flow(
        op_sys="centos6",
        min_size="13",
        max_size="14",
        master_instance="t2.nano",
        compute_instance="t2.micro",
        key="key1",
    )
    input_composer.add_sub_automation(
        vpc_id="vpc-12345678", network_configuration=PUBLIC_PRIVATE_CONFIGURATION, vpc_has_subnets=True
    )
    input_composer.finalize_config(mocker)

    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_subnet_automation_no_awsbatch_no_errors_with_config_file(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)
    old_config_file = str(test_datadir / "original_config_file")

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789")
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="sge")
    input_composer.add_first_flow(
        op_sys="centos6",
        min_size="13",
        max_size="14",
        master_instance="t2.nano",
        compute_instance="t2.micro",
        key="key1",
    )
    input_composer.add_sub_automation(
        vpc_id="vpc-12345678", network_configuration=PUBLIC_PRIVATE_CONFIGURATION, vpc_has_subnets=True
    )
    input_composer.finalize_config(mocker)

    _launch_config(mocker, old_config_file, remove_path=False)
    assert_that(_are_configurations_equals(old_config_file, config)).is_true()
    _are_output_error_correct(capsys, output, error, old_config_file)
    os.remove(old_config_file)


def test_vpc_automation_no_awsbatch_no_errors(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789")
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="sge")
    input_composer.add_first_flow(
        op_sys="centos6",
        min_size="13",
        max_size="14",
        master_instance="t2.nano",
        compute_instance="t2.micro",
        key="key1",
    )
    input_composer.add_vpc_sub_automation(network_configuration=PUBLIC_PRIVATE_CONFIGURATION)
    input_composer.finalize_config(mocker)

    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_vpc_automation_yes_awsbatch_no_errors(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789")
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="awsbatch")
    input_composer.add_first_flow(
        op_sys=None, min_size="13", max_size="14", master_instance="t2.nano", compute_instance=None, key="key1"
    )
    input_composer.add_vpc_sub_automation(network_configuration=PUBLIC_PRIVATE_CONFIGURATION)
    input_composer.finalize_config(mocker)

    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_vpc_automation_invalid_vpc_block(mocker, capsys, test_datadir):
    with pytest.raises(SystemExit):
        config, error, output = get_file_path(test_datadir)

        mock_handler = MockHandler(mocker)
        mock_handler.add_subnet_automation(
            public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789", is_a_valid_vpc=False
        )
        input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="awsbatch")
        input_composer.add_first_flow(
            op_sys=None, min_size="13", max_size="14", master_instance="t2.nano", compute_instance=None, key="key1"
        )
        input_composer.add_vpc_sub_automation(network_configuration=PUBLIC_PRIVATE_CONFIGURATION)
        input_composer.finalize_config(mocker)
        _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_subnet_automation_yes_awsbatch_invalid_vpc(mocker, capsys, test_datadir, caplog):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(
        public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789", is_a_valid_vpc=False
    )
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="awsbatch")
    input_composer.add_first_flow(
        op_sys=None, min_size="13", max_size="14", master_instance="t2.nano", compute_instance=None, key="key1"
    )
    input_composer.add_sub_automation(vpc_id="vpc-12345678", network_configuration=PUBLIC_PRIVATE_CONFIGURATION)
    input_composer.finalize_config(mocker)
    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)
    assert_that("WARNING: The VPC does not have the correct parameters set." in caplog.text).is_true()


def test_vpc_automation_no_vpc_in_region(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker, empty_region=True)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678", private_subnet_id="subnet-23456789")
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="slurm")
    input_composer.add_first_flow(
        op_sys="centos6",
        min_size="13",
        max_size="14",
        master_instance="t2.nano",
        compute_instance="t2.micro",
        key="key1",
    )
    input_composer.add_vpc_sub_automation_empty_region(network_configuration=PUBLIC_PRIVATE_CONFIGURATION)
    input_composer.finalize_config(mocker)

    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_vpc_automation_no_vpc_in_region_public(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker, empty_region=True)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-12345678")
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="slurm")
    input_composer.add_first_flow(
        op_sys="centos6",
        min_size="13",
        max_size="14",
        master_instance="t2.nano",
        compute_instance="t2.micro",
        key="key1",
    )
    input_composer.add_vpc_sub_automation_empty_region(network_configuration="2")
    input_composer.finalize_config(mocker)

    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def general_wrapper_for_prompt_testing(
    mocker,
    region="eu-west-1",
    scheduler="torque",
    op_sys="centos6",
    min_size="0",
    max_size="10",
    master_instance="t2.nano",
    compute_instance="t2.micro",
    key="key1",
    vpc_id="vpc-12345678",
    master_id="subnet-12345678",
    compute_id="subnet-23456789",
):
    path = os.path.join(tempfile.gettempdir(), "test_pcluster_configure")
    MockHandler(mocker)
    input_composer = ComposeInput(aws_region_name=region, scheduler=scheduler)
    input_composer.add_first_flow(op_sys, min_size, max_size, master_instance, compute_instance, key)
    input_composer.add_no_automation_no_empty_vpc(vpc_id, master_id, compute_id)
    input_composer.finalize_config(mocker)

    _launch_config(mocker, path)
    return True


def test_min_max(mocker):
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, min_size="17", max_size="16")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, min_size="-17", max_size="16")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, min_size="1", max_size="-16")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, min_size="1", max_size="1.6")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, min_size="1", max_size="1,6")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, min_size="schrodinger", max_size="16")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, min_size="12", max_size="cat")
    with pytest.raises(StopIteration):
        greater_than_default = "2500"
        default = ""
        general_wrapper_for_prompt_testing(mocker, min_size=greater_than_default, max_size=default)

    assert_that(general_wrapper_for_prompt_testing(mocker, min_size="", max_size="")).is_true()
    assert_that(general_wrapper_for_prompt_testing(mocker, min_size="1", max_size="2")).is_true()
    assert_that(general_wrapper_for_prompt_testing(mocker, min_size="", max_size="1")).is_true()
    assert_that(general_wrapper_for_prompt_testing(mocker, min_size="4", max_size="")).is_true()


def test_prompt_a_list(mocker):
    # Remember that keys go from key1...key6
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, key="key0")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, key="key7")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, key="0")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, key="-1")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, key="-17")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, key="8")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, key="sopralapancalacapracampa")

    for i in range(1, 7):
        assert_that(general_wrapper_for_prompt_testing(mocker, key="key" + str(i))).is_true()
        assert_that(general_wrapper_for_prompt_testing(mocker, key=str(i))).is_true()


def test_prompt_a_list_of_tuple(mocker):
    # Look at _mock_list_vpcs and subnets
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, vpc_id="2 subnets inside")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, vpc_id="ParallelClusterVPC-20190625135738")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, vpc_id="vpc-0")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, vpc_id="vpc-7")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, vpc_id="0")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, vpc_id="-1")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, vpc_id="-17")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, vpc_id="8")
    with pytest.raises(StopIteration):
        general_wrapper_for_prompt_testing(mocker, vpc_id="sopralapancalacapracampa")

    # TODO use parametrize
    # invalid subnets
    with pytest.raises(StopIteration):
        assert_that(
            general_wrapper_for_prompt_testing(
                mocker, vpc_id="vpc-12345678", master_id="subnet-34567891", compute_id="subnet-45678912"
            )
        ).is_true()
    with pytest.raises(StopIteration):
        assert_that(
            general_wrapper_for_prompt_testing(
                mocker, vpc_id="vpc-23456789", master_id="subnet-34567891", compute_id="subnet-45678912"
            )
        ).is_true()
    with pytest.raises(StopIteration):
        assert_that(
            general_wrapper_for_prompt_testing(
                mocker, vpc_id="vpc-34567891", master_id="subnet-12345678", compute_id="subnet-23456789"
            )
        ).is_true()

    # valid subnets
    assert_that(
        general_wrapper_for_prompt_testing(
            mocker, vpc_id="vpc-12345678", master_id="subnet-12345678", compute_id="subnet-23456789"
        )
    ).is_true()
    assert_that(
        general_wrapper_for_prompt_testing(
            mocker, vpc_id="vpc-34567891", master_id="subnet-45678912", compute_id="subnet-45678912"
        )
    ).is_true()
