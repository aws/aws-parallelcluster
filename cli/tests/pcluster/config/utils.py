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
import shutil
import tempfile

import configparser
import pytest
from configparser import NoOptionError, NoSectionError

from assertpy import assert_that
from pcluster.config.param_types import Param
from pcluster.config.pcluster_config import PclusterConfig
from tests.pcluster.config.defaults import CFN_CONFIG_NUM_OF_PARAMS, DefaultDict

# List of parameters ignored by default when comparing sections
COMPARATION_IGNORED_PARAMS = ["ClusterConfigMetadata"]


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


def set_default_values_for_required_cluster_section_params(cluster_section_dict, only_if_not_present=False):
    """
    Provide default values for required parameters for the cluster section.

    This is useful for the cluster section of the config file because, unlike the CFN template,
    there are no default values defined in mappings.py or in the defaults module used for testing.

    If only_if_not_present is set, then the default values are only added if the
    cluster_section_dict does not contain keys for the required parameters. Otherwise a default is
    only set if the value is None.
    """
    required_cluster_params = [
        {"key": "scheduler", "value": "slurm"},
        {"key": "base_os", "value": "alinux2"},
    ]
    for required_param in required_cluster_params:
        if only_if_not_present:
            cluster_section_dict.setdefault(required_param.get("key"), required_param.get("value"))
        elif cluster_section_dict.get(required_param.get("key")) is None:
            cluster_section_dict[required_param.get("key")] = required_param.get("value")


def assert_param_from_file(
    mocker, section_definition, param_key, param_value, expected_value, expected_message, do_validation=False
):
    section_label = section_definition.get("default_label")
    section_name = "{0}{1}".format(section_definition.get("key"), " {0}".format(section_label) if section_label else "")
    config_parser = configparser.ConfigParser()
    config_parser.add_section(section_name)

    pcluster_config = get_mocked_pcluster_config(mocker)

    if param_value is not None:
        config_parser.set(section_name, param_key, param_value)

    param_definition, param_type = get_param_definition(section_definition, param_key)

    if expected_message:
        with pytest.raises(SystemExit, match=expected_message):
            param = param_type(
                section_definition.get("key"), section_label, param_key, param_definition, pcluster_config
            ).from_file(config_parser)
            if do_validation:
                param.validate()
    else:
        param = param_type(
            section_definition.get("key"), section_label, param_key, param_definition, pcluster_config
        ).from_file(config_parser)
        if do_validation:
            param.validate()
        assert_that(param.value, description="{0} assert fail".format(param.key)).is_equal_to(expected_value)


def get_mock_pcluster_config_patches(scheduler, extra_patches=None):
    """Return mocks for a set of functions that should be mocked by default because they access the network."""
    architectures = ["x86_64"]
    master_instances = ["t2.micro", "t2.large", "c4.xlarge"]
    compute_instances = ["t2.micro", "t2.large", "t2", "optimal"] if scheduler == "awsbatch" else master_instances
    patches = {
        "pcluster.config.validators.get_supported_instance_types": master_instances,
        "pcluster.config.validators.get_supported_compute_instance_types": compute_instances,
        "pcluster.config.validators.get_supported_architectures_for_instance_type": architectures,
        "pcluster.config.param_types.get_avail_zone": "mocked_avail_zone",
        "pcluster.config.param_types.get_supported_architectures_for_instance_type": architectures,
        "pcluster.config.validators.get_instance_vcpus": 1,
    }
    if extra_patches:
        patches = merge_dicts(patches, extra_patches)
    return patches


def mock_pcluster_config(mocker, scheduler=None, extra_patches=None, patch_funcs=None):
    """Mock various components used to instantiate an instance of PclusterConfig."""
    mock_patches = get_mock_pcluster_config_patches(scheduler, extra_patches)
    for function, return_value in mock_patches.items():
        mocker.patch(function, return_value=return_value)
    mocker.patch.object(PclusterConfig, "_PclusterConfig__test_configuration")


def assert_param_validator(
    mocker, config_parser_dict, expected_error=None, capsys=None, expected_warning=None, extra_patches=None,
):
    config_parser = configparser.ConfigParser()

    # These parameters are required, meaning a value must be specified or an exception is raised.
    # Provide the default values that `pcluster configure` would suggest.
    set_default_values_for_required_cluster_section_params(
        config_parser_dict.get("cluster default"), only_if_not_present=True
    )
    config_parser.read_dict(config_parser_dict)

    mock_pcluster_config(mocker, config_parser_dict.get("cluster default").get("scheduler"), extra_patches)
    if expected_error:
        with pytest.raises(SystemExit, match=expected_error):
            _ = init_pcluster_config_from_configparser(config_parser)
    else:
        _ = init_pcluster_config_from_configparser(config_parser)
        if expected_warning:
            assert_that(capsys).is_not_none()
            assert_that(capsys.readouterr().out).matches(expected_warning)


def assert_section_from_cfn(mocker, section_definition, cfn_params_dict, expected_section_dict):
    def mock_get_avail_zone(subnet_id):
        # Mock az detection by returning a mock az if subnet has a value
        return "my-avail-zone" if subnet_id and subnet_id != "NONE" else None

    mocker.patch("pcluster.config.param_types.get_avail_zone", mock_get_avail_zone)
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


def get_mocked_pcluster_config(mocker, auto_refresh=False):
    mocker.patch("pcluster.config.param_types.get_supported_architectures_for_instance_type", return_value=["x86_64"])
    pcluster_config = PclusterConfig(config_file="wrong-file")
    pcluster_config.set_auto_refresh(auto_refresh)
    return pcluster_config


def assert_section_from_file(mocker, section_definition, config_parser_dict, expected_dict_params, expected_message):
    mocker.patch("pcluster.config.param_types.get_supported_architectures_for_instance_type", return_value=["x86_64"])
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


def remove_ignored_params(dict, ignored_params=COMPARATION_IGNORED_PARAMS):
    """
    Remove ignored parameters from a dict of params.

    :param dict: The parameters dictionary
    :param ignored_params: The parameters keys to remove
    """
    for ignored_param in ignored_params:
        dict.pop(ignored_param, None)


def assert_section_to_cfn(mocker, section_definition, section_dict, expected_cfn_params, ignore_metadata=True):
    # auto_refresh is disabled if config metadata is ignored to save unnecessary cycles
    pcluster_config = get_mocked_pcluster_config(mocker, auto_refresh=not ignore_metadata)

    section_type = section_definition.get("type")
    section = section_type(section_definition, pcluster_config)
    for param_key, param_value in section_dict.items():
        param_definition, param_type = get_param_definition(section_definition, param_key)
        param = param_type(section_definition.get("key"), "default", param_key, param_definition, pcluster_config)
        param.value = param_value
        section.add_param(param)
    pcluster_config.add_section(section)

    cfn_params = section.to_cfn()
    if ignore_metadata:
        remove_ignored_params(cfn_params)
        remove_ignored_params(expected_cfn_params)

    assert_that(cfn_params).is_equal_to(expected_cfn_params)


def assert_section_params(mocker, pcluster_config_reader, settings_label, expected_cfn_params):
    mocker.patch("pcluster.config.param_types.get_supported_architectures_for_instance_type", return_value=["x86_64"])
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

        remove_ignored_params(cfn_params)

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


def duplicate_config_file(dst_config_file, test_datadir):
    # Make a copy of the src template to the target file.
    # The two resulting PClusterConfig instances will be identical
    src_config_file_path = os.path.join(str(test_datadir), "pcluster.config.ini")
    dst_config_file_path = os.path.join(str(test_datadir), dst_config_file)
    shutil.copy(src_config_file_path, dst_config_file_path)
