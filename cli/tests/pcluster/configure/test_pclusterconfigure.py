import os
import tempfile

import pytest
from configparser import ConfigParser

from assertpy import assert_that
from pcluster.configure.easyconfig import configure

EASYCONFIG = "pcluster.configure.easyconfig."
NETWORKING = "pcluster.configure.easyconfig_networking."
UTILS = "pcluster.configure.easyconfig_utils."

TEMP_PATH_FOR_CONFIG = os.path.join(tempfile.gettempdir(), "test_pclusterconfigure")


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
    mocker.patch(EASYCONFIG + "_list_keys", return_value=keys)


def _mock_list_vpcs_and_subnets(mocker, empty_region=False):
    # If changed look for test_prompt_a_list_of_tuple
    if empty_region:
        dict = {"vpc_list": [], "vpc_to_subnets": {}}
    else:
        dict = {
            "vpc_list": [
                ("vpc-1", "ParallelClusterVPC-20190625135738", "2 subnets inside"),
                ("vpc-2", "ParallelClusterVPC-20190624105051", "0 subnets inside"),
                ("vpc-3", "default", "3 subnets inside"),
                ("vpc-4", "ParallelClusterVPC-20190626095403", "1 subnets inside"),
            ],
            "vpc_to_subnets": {
                "vpc-1": [
                    ("subnet-11", "ParallelClusterPublicSubnet", "Subnet size: 256"),
                    ("subnet-12", "ParallelClusterPrivateSubnet", "Subnet size: 4096"),
                ],
                "vpc-2": [],
                "vpc-3": [
                    ("subnet-31", "Subnet size: 4096"),
                    ("subnet-32", "Subnet size: 4096"),
                    ("subnet-33", "Subnet size: 4096"),
                ],
                "vpc-4": [("subnet-41", "ParallelClusterPublicSubnet", "Subnet size: 4096")],
            },
        }
    mocker.patch(EASYCONFIG + "_list_vpcs_and_subnets", return_value=dict)


def _mock_get_subnets_in_vpc(mocker):
    mocker.patch(NETWORKING + "_get_subnets_in_vpc", return_value=[])


def _mock_vpc_factory(mocker, is_a_valid_vpc):
    vpc_factory = NETWORKING + "VpcFactory"
    mock = mocker.patch(vpc_factory, autospec=True)
    mock.return_value.create.return_value = "vpc-0"
    mock.return_value.check.return_value = is_a_valid_vpc


def _mock_ec2_conn(mocker):
    mocker.patch(NETWORKING + "_extract_vpc_cidr", return_value="10.0.0.0/16")
    mocker.patch(NETWORKING + "_extract_ig_id", return_value="ig-123")


def _mock_create_network_configuration(mocker, public_subnet_id, private_subnet_id=None):
    def _side_effect_function(template_name, configurer, also_private_cidr):
        if private_subnet_id:
            return [
                {"OutputKey": "PrivateSubnetId", "OutputValue": private_subnet_id},
                {"OutputKey": "PublicSubnetId", "OutputValue": public_subnet_id},
            ]
        else:
            return [{"OutputKey": "PublicSubnetId", "OutputValue": public_subnet_id}]

    mocker.patch(NETWORKING + "_create_network_configuration", side_effect=_side_effect_function)


def _launch_config(mocker, path, remove_path=True):
    if remove_path and os.path.isfile(path):
        os.remove(path)
    args = mocker.Mock
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
            if dict2[section_name][key] != value:
                return False
    return True


def _write_output_and_error(capsys, error_path, output_path):
    readouterr = capsys.readouterr()
    with open(error_path, "w+") as file:
        file.write(readouterr.err)
    with open(output_path, "w+") as file:
        file.write(readouterr.out)


def _are_output_error_correct(capsys, output, error):
    readouterr = capsys.readouterr()
    with open(output) as f:
        assert_that(readouterr.out).is_equal_to(f.read())
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

    def add_subnet_automation(self, public_subnet_id, is_a_valid_vpc=True, private_subnet_id=None):
        _mock_vpc_factory(self.mocker, is_a_valid_vpc)
        _mock_get_subnets_in_vpc(self.mocker)
        _mock_ec2_conn(self.mocker)
        _mock_create_network_configuration(self.mocker, public_subnet_id, private_subnet_id)


def get_file_path(test_datadir):
    config = os.path.join(test_datadir, "test")
    output = os.path.join(test_datadir, "output.txt")
    error = os.path.join(test_datadir, "error.txt")
    return config, error, output


def _verify_test(mocker, capsys, output, error, config, temp_path_for_config):
    _launch_config(mocker, temp_path_for_config)
    assert_that(_are_configurations_equals(temp_path_for_config, config)).is_true()
    _are_output_error_correct(capsys, output, error)
    os.remove(temp_path_for_config)


# note that user_prompt passed to input will not be shown.
def create_new_test(mocker, capsys):
    """
    Create a new test for the pcluster configure.

    You have to be sure that pcluster configure is correct when you use this function. You will also have to check
    output manually. Note that it does not print user_prompt passed as input, but neither does all the tests
    """
    test_name = "test_vpc_automation_no_vpc_in_region"
    config_path = os.path.join(os.getcwd(), "test_pclusterconfigure", test_name, "test")
    error_path = os.path.join(os.getcwd(), "test_pclusterconfigure", test_name, "error.txt")
    output_path = os.path.join(os.getcwd(), "test_pclusterconfigure", test_name, "output.txt")

    mock_handler = MockHandler(mocker, empty_region=True)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-pu", private_subnet_id="subnet-pr")
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="slurm")
    input_composer.add_first_flow(
        op_sys="centos6",
        min_size="13",
        max_size="14",
        master_instance="t2.nano",
        compute_instance="t2.micro",
        key="key1",
    )
    input_composer.add_vpc_sub_automation_empty_region(network_configuration="1")
    input_composer.finalize_config(mocker)

    _launch_config(mocker, config_path)
    _write_output_and_error(capsys, error_path, output_path)
    assert_that(True).is_true()


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
    input_composer.add_no_automation_no_empty_vpc(vpc_id="vpc-1", master_id="subnet-11", compute_id="subnet-12")
    input_composer.finalize_config(mocker)

    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_no_automation_yes_awsbatch_no_errors(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    MockHandler(mocker)
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="awsbatch")
    input_composer.add_first_flow(
        op_sys=None, min_size="13", max_size="14", master_instance="t2.nano", compute_instance=None, key="key1"
    )
    input_composer.add_no_automation_no_empty_vpc(vpc_id="vpc-1", master_id="subnet-11", compute_id="subnet-12")
    input_composer.finalize_config(mocker)

    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_subnet_automation_no_awsbatch_no_errors_empty_vpc(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-pu", private_subnet_id="subnet-pr")
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="sge")
    input_composer.add_first_flow(
        op_sys="centos6",
        min_size="13",
        max_size="14",
        master_instance="t2.nano",
        compute_instance="t2.micro",
        key="key1",
    )
    input_composer.add_sub_automation(vpc_id="vpc-2", network_configuration="1", vpc_has_subnets=False)
    input_composer.finalize_config(mocker)

    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_subnet_automation_no_awsbatch_no_errors(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-pu", private_subnet_id="subnet-pr")
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="sge")
    input_composer.add_first_flow(
        op_sys="centos6",
        min_size="13",
        max_size="14",
        master_instance="t2.nano",
        compute_instance="t2.micro",
        key="key1",
    )
    input_composer.add_sub_automation(vpc_id="vpc-1", network_configuration="1", vpc_has_subnets=True)
    input_composer.finalize_config(mocker)

    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_subnet_automation_no_awsbatch_no_errors_with_config_file(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)
    old_config_file = test_datadir / "original_config_file"

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-pu", private_subnet_id="subnet-pr")
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="sge")
    input_composer.add_first_flow(
        op_sys="centos6",
        min_size="13",
        max_size="14",
        master_instance="t2.nano",
        compute_instance="t2.micro",
        key="key1",
    )
    input_composer.add_sub_automation(vpc_id="vpc-1", network_configuration="1", vpc_has_subnets=True)
    input_composer.finalize_config(mocker)

    _launch_config(mocker, old_config_file, remove_path=False)
    assert_that(_are_configurations_equals(old_config_file, config)).is_true()
    _are_output_error_correct(capsys, output, error)
    os.remove(old_config_file)


def test_vpc_automation_no_awsbatch_no_errors(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-pu", private_subnet_id="subnet-pr")
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="sge")
    input_composer.add_first_flow(
        op_sys="centos6",
        min_size="13",
        max_size="14",
        master_instance="t2.nano",
        compute_instance="t2.micro",
        key="key1",
    )
    input_composer.add_vpc_sub_automation(network_configuration="1")
    input_composer.finalize_config(mocker)

    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_vpc_automation_yes_awsbatch_no_errors(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-pu", private_subnet_id="subnet-pr")
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="awsbatch")
    input_composer.add_first_flow(
        op_sys=None, min_size="13", max_size="14", master_instance="t2.nano", compute_instance=None, key="key1"
    )
    input_composer.add_vpc_sub_automation(network_configuration="1")
    input_composer.finalize_config(mocker)

    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_vpc_automation_invalid_vpc_block(mocker, capsys, test_datadir):
    with pytest.raises(SystemExit):
        config, error, output = get_file_path(test_datadir)

        mock_handler = MockHandler(mocker)
        mock_handler.add_subnet_automation(
            public_subnet_id="subnet-pu", private_subnet_id="subnet-pr", is_a_valid_vpc=False
        )
        input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="awsbatch")
        input_composer.add_first_flow(
            op_sys=None, min_size="13", max_size="14", master_instance="t2.nano", compute_instance=None, key="key1"
        )
        input_composer.add_vpc_sub_automation(network_configuration="1")
        input_composer.finalize_config(mocker)
        _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)


def test_subnet_automation_yes_awsbatch_invalid_vpc(mocker, capsys, test_datadir, caplog):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker)
    mock_handler.add_subnet_automation(
        public_subnet_id="subnet-pu", private_subnet_id="subnet-pr", is_a_valid_vpc=False
    )
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="awsbatch")
    input_composer.add_first_flow(
        op_sys=None, min_size="13", max_size="14", master_instance="t2.nano", compute_instance=None, key="key1"
    )
    input_composer.add_sub_automation(vpc_id="vpc-1", network_configuration="1")
    input_composer.finalize_config(mocker)
    _verify_test(mocker, capsys, output, error, config, TEMP_PATH_FOR_CONFIG)
    assert_that("WARNING: The vpc does not have the correct parameters set." in caplog.text).is_true()


def test_vpc_automation_no_vpc_in_region(mocker, capsys, test_datadir):
    config, error, output = get_file_path(test_datadir)

    mock_handler = MockHandler(mocker, empty_region=True)
    mock_handler.add_subnet_automation(public_subnet_id="subnet-pu", private_subnet_id="subnet-pr")
    input_composer = ComposeInput(aws_region_name="eu-west-1", scheduler="slurm")
    input_composer.add_first_flow(
        op_sys="centos6",
        min_size="13",
        max_size="14",
        master_instance="t2.nano",
        compute_instance="t2.micro",
        key="key1",
    )
    input_composer.add_vpc_sub_automation_empty_region(network_configuration="1")
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
    vpc_id="vpc-1",
    master_id="subnet-11",
    compute_id="subnet-12",
):
    path = os.path.join(tempfile.gettempdir(), "test_pclusterconfigure")
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

    for i in range(1, 5):
        i_s = str(i)
        if i == 2:
            with pytest.raises(StopIteration):
                assert_that(
                    general_wrapper_for_prompt_testing(
                        mocker,
                        vpc_id="vpc-" + i_s,
                        master_id="subnet-{0}1".format(i_s),
                        compute_id="subnet-{0}1".format(i_s),
                    )
                ).is_true()
                assert_that(
                    general_wrapper_for_prompt_testing(
                        mocker, vpc_id=i_s, master_id="subnet-{0}1".format(i_s), compute_id="subnet-{0}1".format(i_s)
                    )
                ).is_true()
        else:
            assert_that(
                general_wrapper_for_prompt_testing(
                    mocker,
                    vpc_id="vpc-" + i_s,
                    master_id="subnet-{0}1".format(i_s),
                    compute_id="subnet-{0}1".format(i_s),
                )
            ).is_true()
            assert_that(
                general_wrapper_for_prompt_testing(
                    mocker, vpc_id=i_s, master_id="subnet-{0}1".format(i_s), compute_id="subnet-{0}1".format(i_s)
                )
            ).is_true()
