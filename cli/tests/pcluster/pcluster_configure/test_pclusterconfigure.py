import pytest
import pcluster.easyconfig
import pcluster.cfnconfig
import os
import tempfile

from configparser import ConfigParser
from assertpy import assert_that


def _check_error(capsys, error):
    out = capsys.readouterr()[0].splitlines()
    assert_that(out[len(out) - 2]).is_equal_to(f"ERROR: The value ({error}) is not valid ")


def _override_list_resource(mocker, values, resource):
    mocker.patch(f"pcluster.easyconfig.list_{resource}", return_value=values)


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


def _create_user_input(cluster_template, region, vpc_name, key, vpc_id, subnet_id):
    return cluster_template, region, vpc_name, key, vpc_id, subnet_id


def _launcher(mocker, input_list, keys_allowed, vpcs_allowed, subnets_allowed, expected_template):
    temp_path = os.path.join(tempfile.gettempdir(), "test_configure")
    if os.path.isfile(temp_path):
        os.remove(temp_path)
    mocker.patch("pcluster.easyconfig.input", side_effect=input_list)
    mocker.patch("pcluster.cfnconfig.ParallelClusterConfig")
    _override_list_resource(mocker, keys_allowed, "keys")
    _override_list_resource(mocker, vpcs_allowed, "vpcs")
    _override_list_resource(mocker, subnets_allowed, "subnets")
    args = mocker.Mock
    args.config_file = temp_path
    pcluster.easyconfig.configure(args)
    return _are_configurations_equals(temp_path, expected_template)


def test_wrong_insert(mocker, shared_datadir, capsys):
    error = "keyB"
    with pytest.raises(SystemExit):
        assert_that(_launcher(
            mocker,
            _create_user_input(
                cluster_template="fdsgdsa",
                region="eu-west-1",
                vpc_name="gfdgfd",
                key="keyB",
                vpc_id="vpc-03c69bdea85428d46",
                subnet_id="subnet-08a405e8c17eb79af",
            ),
            ["keyA"],
            ["vpc-03c69bdea85428d46"],
            ["subnet-08a405e8c17eb79af"],
            (shared_datadir / "normal_flow"),
        )).is_true()
    _check_error(capsys, error)

    error = "vpc-nottheone"
    with pytest.raises(SystemExit):
        assert_that(_launcher(
            mocker,
            _create_user_input(
                cluster_template="fdsgdsa",
                region="eu-west-1",
                vpc_name="gfdgfd",
                key="test-euwest1-key",
                vpc_id="vpc-nottheone",
                subnet_id="subnet-08a405e8c17eb79af",
            ),
            ["test-euwest1-key"],
            ["vpc-03c69bdea85428d46"],
            ["subnet-08a405e8c17eb79af"],
            (shared_datadir / "normal_flow"),
        )).is_true()
    _check_error(capsys, error)

    error = "subnet-nottheone"
    with pytest.raises(SystemExit):
        assert_that(_launcher(
            mocker,
            _create_user_input(
                cluster_template="fdsgdsa",
                region="eu-west-1",
                vpc_name="gfdgfd",
                key="test-euwest1-key",
                vpc_id="vpc-03c69bdea85428d46",
                subnet_id="subnet-nottheone",
            ),
            ["test-euwest1-key"],
            ["vpc-03c69bdea85428d46"],
            ["subnet-08a405e8c17eb79af"],
            (shared_datadir / "normal_flow"),
        )).is_true()
    _check_error(capsys, error)


def test_normal_flow(mocker, shared_datadir):
    assert_that(_launcher(
        mocker,
        _create_user_input(
            cluster_template="fdsgdsa",
            region="eu-west-1",
            vpc_name="gfdgfd",
            key="test-euwest1-key",
            vpc_id="vpc-03c69bdea85428d46",
            subnet_id="subnet-08a405e8c17eb79af",
        ),
        ["test-euwest1-key"],
        ["vpc-03c69bdea85428d46"],
        ["subnet-08a405e8c17eb79af"],
        (shared_datadir / "normal_flow"),
    )).is_true()
