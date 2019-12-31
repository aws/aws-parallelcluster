# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import os
import tempfile

import configparser
import pytest
from configparser import NoOptionError, NoSectionError

from assertpy import assert_that
from pcluster.config.param_types import Param
from pcluster.config.pcluster_config import PclusterConfig
from tests.pcluster.config.defaults import CFN_CONFIG_NUM_OF_PARAMS, DefaultDict


def get_param_definition(section_definition, param_key):
    param_definition = section_definition.get("params").get(param_key)
    return param_definition, param_definition.get("type", Param)


def merge_dicts(*args):
    """Merge multiple dictionaries into a new dictionary as a shallow copy."""
    merged_dict = {}
    for input_dict in args:
        merged_dict.update(input_dict)
    return merged_dict


def get_pcluster_config_example():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(current_dir, "..", "..", "..", "pcluster", "examples", "config")


def assert_param_from_file(mocker, section_definition, param_key, param_value, expected_value, expected_message):
    section_label = section_definition.get("default_label")
    section_name = "{0}{1}".format(section_definition.get("key"), " {0}".format(section_label) if section_label else "")
    config_parser = configparser.ConfigParser()
    config_parser.add_section(section_name)

    pcluster_config = get_mocked_pcluster_config(mocker)

    if param_value:
        config_parser.set(section_name, param_key, param_value)

    param_definition, param_type = get_param_definition(section_definition, param_key)

    if expected_message:
        with pytest.raises(SystemExit, match=expected_message):
            param_type(
                section_definition.get("key"), section_label, param_key, param_definition, pcluster_config
            ).from_file(config_parser)
    else:
        param = param_type(
            section_definition.get("key"), section_label, param_key, param_definition, pcluster_config
        ).from_file(config_parser)
        assert_that(param.value, description="{0} assert fail".format(param.key)).is_equal_to(expected_value)


def assert_param_validator(mocker, config_parser_dict, expected_error=None, capsys=None, expected_warning=None):
    config_parser = configparser.ConfigParser()
    config_parser.read_dict(config_parser_dict)

    mocker.patch("pcluster.config.param_types.get_avail_zone", return_value="mocked_avail_zone")
    mocker.patch.object(PclusterConfig, "_PclusterConfig__check_account_capacity")

    # Mock IAM policies validator to prevent boto3 calls in tests
    accepted_policies = [
        "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
        "arn:aws:iam::aws:policy/AWSBatchFullAccess",
    ]

    def mock_iam_policies_validate(self):
        """Mock validation: just check that the policy is among the accepted ones."""
        assert set(self.value).issubset(accepted_policies)

    mocker.patch("pcluster.config.param_types.AdditionalIamPoliciesParam.validate", new=mock_iam_policies_validate)

    if expected_error:
        with pytest.raises(SystemExit, match=expected_error):
            _ = init_pcluster_config_from_configparser(config_parser)
    else:
        _ = init_pcluster_config_from_configparser(config_parser)
        if expected_warning:
            assert_that(capsys).is_not_none()
            assert_that(capsys.readouterr().out).matches(expected_warning)


def assert_section_from_cfn(mocker, section_definition, cfn_params_dict, expected_section_dict):

    cfn_params = []
    for cfn_key, cfn_value in cfn_params_dict.items():
        cfn_params.append({"ParameterKey": cfn_key, "ParameterValue": cfn_value})

    pcluster_config = get_mocked_pcluster_config(mocker)

    section_type = section_definition.get("type")
    section = section_type(section_definition, pcluster_config).from_cfn_params(cfn_params)

    if section.label:
        assert_that(section.label).is_equal_to("default")

    # update expected dictionary
    default_dict = DefaultDict[section_definition.get("key")].value
    expected_dict = default_dict.copy()
    if isinstance(expected_section_dict, dict):
        expected_dict.update(expected_section_dict)

    section_dict = {}
    for param_key, param in section.params.items():
        section_dict[param_key] = param.value

    assert_that(section_dict).is_equal_to(expected_dict)


def get_mocked_pcluster_config(mocker):
    return PclusterConfig(config_file="wrong-file")


def assert_section_from_file(mocker, section_definition, config_parser_dict, expected_dict_params, expected_message):
    config_parser = configparser.ConfigParser()
    config_parser.read_dict(config_parser_dict)

    # update expected dictionary
    default_dict_key = section_definition.get("key")
    if default_dict_key == "global":
        default_dict_key += "_"
    default_dict = DefaultDict[default_dict_key].value

    expected_dict = default_dict.copy()

    if isinstance(expected_dict_params, dict):
        expected_dict.update(expected_dict_params)

    pcluster_config = get_mocked_pcluster_config(mocker)

    section_type = section_definition.get("type")
    if expected_message:
        with pytest.raises(SystemExit, match=expected_message):
            _ = section_type(section_definition, pcluster_config).from_file(config_parser)
    else:
        section = section_type(section_definition, pcluster_config).from_file(config_parser)
        section_dict = {}
        for param_key, param in section.params.items():
            section_dict[param_key] = param.value

        assert_that(section_dict).is_equal_to(expected_dict)


def assert_section_to_file(mocker, section_definition, section_dict, expected_config_parser_dict, expected_message):
    expected_config_parser = configparser.ConfigParser()
    expected_config_parser.read_dict(expected_config_parser_dict)

    pcluster_config = get_mocked_pcluster_config(mocker)

    output_config_parser = configparser.ConfigParser()
    section_type = section_definition.get("type")
    section = section_type(section_definition, pcluster_config, section_label="default")

    for param_key, param_value in section_dict.items():
        param_definition, param_type = get_param_definition(section.definition, param_key)
        param = param_type(section_definition.get("key"), "default", param_key, param_definition, pcluster_config)
        param.value = param_value
        section.add_param(param)

    section.to_file(output_config_parser)

    for section_key, section_params in expected_config_parser_dict.items():
        for param_key, param_value in section_params.items():

            assert_that(output_config_parser.has_option(section_key, param_key))
            if expected_message is not None:
                if "No section" in expected_message:
                    with pytest.raises(NoSectionError, match=expected_message):
                        assert_that(output_config_parser.get(section_key, param_key)).is_equal_to(param_value)
                else:
                    with pytest.raises(NoOptionError, match=expected_message):
                        assert_that(output_config_parser.get(section_key, param_key)).is_equal_to(param_value)

            else:
                assert_that(output_config_parser.get(section_key, param_key)).is_equal_to(param_value)


def assert_section_to_cfn(mocker, section_definition, section_dict, expected_cfn_params):

    pcluster_config = get_mocked_pcluster_config(mocker)

    section_type = section_definition.get("type")
    section = section_type(section_definition, pcluster_config)
    for param_key, param_value in section_dict.items():
        param_definition, param_type = get_param_definition(section_definition, param_key)
        param = param_type(section_definition.get("key"), "default", param_key, param_definition, pcluster_config)
        param.value = param_value
        section.add_param(param)
    pcluster_config.add_section(section)

    cfn_params = section.to_cfn()
    assert_that(cfn_params).is_equal_to(expected_cfn_params)


def assert_section_params(mocker, pcluster_config_reader, settings_label, expected_cfn_params):
    if isinstance(expected_cfn_params, SystemExit):
        with pytest.raises(SystemExit):
            PclusterConfig(
                cluster_label="default",
                config_file=pcluster_config_reader(settings_label=settings_label),
                fail_on_file_absence=True,
                fail_on_error=True,
            )
    else:
        pcluster_config = PclusterConfig(
            config_file=pcluster_config_reader(settings_label=settings_label), fail_on_file_absence=True
        )

        cfn_params = pcluster_config.to_cfn()

        assert_that(len(cfn_params)).is_equal_to(CFN_CONFIG_NUM_OF_PARAMS)

        for param_key, _ in cfn_params.items():
            assert_that(cfn_params.get(param_key), description=param_key).is_equal_to(
                expected_cfn_params.get(param_key)
            )


def init_pcluster_config_from_configparser(config_parser, validate=True):
    with tempfile.NamedTemporaryFile(delete=False) as config_file:

        with open(config_file.name, "w") as cf:
            config_parser.write(cf)

        pcluster_config = PclusterConfig(
            config_file=config_file.name, cluster_label="default", fail_on_file_absence=True
        )
        if validate:
            pcluster_config.validate()
    return pcluster_config
