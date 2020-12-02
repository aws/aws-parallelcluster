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
from collections import OrderedDict

import configparser
import pytest
from assertpy import assert_that
from configparser import NoOptionError, NoSectionError

from pcluster.cluster_model import ClusterModel
from pcluster.config.cfn_param_types import CfnParam
from pcluster.config.param_types import StorageData
from pcluster.config.pcluster_config import PclusterConfig
from pcluster.utils import InstanceTypeInfo
from tests.pcluster.config.defaults import CFN_HIT_CONFIG_NUM_OF_PARAMS, CFN_SIT_CONFIG_NUM_OF_PARAMS, DefaultDict

# List of parameters ignored by default when comparing sections
COMPARATION_IGNORED_PARAMS = [
    "ClusterConfigMetadata",  # Difficult to test among the other params. Has a specifically dedicated test
    "_scaledown_idletime",  # Automatically managed, contains just a copy of scaledown_idletime for S3 configuration
]


def get_cfnparam_definition(section_definition, param_key):
    param_definition = section_definition.get("params").get(param_key)
    return param_definition, param_definition.get("type", CfnParam)


def merge_dicts(*args):
    """Merge multiple dictionaries into a new dictionary as a shallow copy."""
    merged_dict = {}
    for input_dict in args:
        merged_dict.update(input_dict)
    return merged_dict


def get_pcluster_config_example():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(current_dir, "..", "..", "..", "src", "pcluster", "examples", "config")


def set_default_values_for_required_cluster_section_params(cluster_section_dict, only_if_not_present=False):
    """
    Provide default values for required parameters for the cluster section.

    This is useful for the cluster section of the config file because, unlike the CFN template,
    there are no default values defined in mappings.py or in the defaults module used for testing.

    If only_if_not_present is set, then the default values are only added if the
    cluster_section_dict does not contain keys for the required parameters. Otherwise a default is
    only set if the value is None.
    """
    required_cluster_params = [{"key": "scheduler", "value": "slurm"}, {"key": "base_os", "value": "alinux2"}]
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

    param_definition, param_type = get_cfnparam_definition(section_definition, param_key)

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
    head_node_instances = ["t2.micro", "t2.large", "c4.xlarge", "p4d.24xlarge"]
    compute_instances = ["t2.micro", "t2.large", "t2", "optimal"] if scheduler == "awsbatch" else head_node_instances
    patches = {
        "pcluster.config.validators.get_supported_instance_types": head_node_instances,
        "pcluster.config.validators.get_supported_compute_instance_types": compute_instances,
        "pcluster.config.validators.get_supported_architectures_for_instance_type": architectures,
        "pcluster.config.cfn_param_types.get_availability_zone_of_subnet": "mocked_avail_zone",
        "pcluster.config.cfn_param_types.get_supported_architectures_for_instance_type": architectures,
        "pcluster.config.cfn_param_types.InstanceTypeInfo.init_from_instance_type": InstanceTypeInfo(
            {
                "VCpuInfo": {"DefaultVCpus": 96, "DefaultCores": 48, "DefaultThreadsPerCore": 2},
                "NetworkInfo": {"EfaSupported": True, "MaximumNetworkCards": 1},
            }
        ),
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


def mock_instance_type_info(mocker, instance_type="t2.micro"):
    mocker.patch(
        "pcluster.utils.InstanceTypeInfo.init_from_instance_type",
        return_value=InstanceTypeInfo(
            {
                "InstanceType": instance_type,
                "VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2},
                "NetworkInfo": {"EfaSupported": False},
            }
        ),
    )


def assert_param_validator(
    mocker,
    config_parser_dict,
    expected_error=None,
    capsys=None,
    expected_warning=None,
    extra_patches=None,
):
    config_parser = configparser.ConfigParser()

    # These parameters are required, meaning a value must be specified or an exception is raised.
    # Provide the default values that `pcluster configure` would suggest.
    set_default_values_for_required_cluster_section_params(
        config_parser_dict.get("cluster default"), only_if_not_present=True
    )
    config_parser.read_dict(config_parser_dict)

    mock_pcluster_config(mocker, config_parser_dict.get("cluster default").get("scheduler"), extra_patches)
    mock_instance_type_info(mocker)

    if expected_error:
        with pytest.raises(SystemExit, match=expected_error):
            _ = init_pcluster_config_from_configparser(config_parser)
    else:
        _ = init_pcluster_config_from_configparser(config_parser)
        if expected_warning:
            assert_that(capsys).is_not_none()
            assert_that(capsys.readouterr().out).matches(expected_warning)


def assert_section_from_cfn(
    mocker, section_definition, cfn_params_dict, expected_section_dict, expected_section_label="default"
):
    def mock_get_avail_zone(subnet_id):
        # Mock az detection by returning a mock az if subnet has a value
        return "my-avail-zone" if subnet_id and subnet_id != "NONE" else None

    mocker.patch("pcluster.config.cfn_param_types.get_availability_zone_of_subnet", mock_get_avail_zone)
    cfn_params = []
    for cfn_key, cfn_value in cfn_params_dict.items():
        cfn_params.append({"ParameterKey": cfn_key, "ParameterValue": cfn_value})

    pcluster_config = get_mocked_pcluster_config(mocker)

    section_type = section_definition.get("type")
    storage_params = StorageData(cfn_params, None)
    section = section_type(section_definition, pcluster_config).from_storage(storage_params)

    if section.label:
        assert_that(section.label).is_equal_to(expected_section_label)

    # update expected dictionary
    default_dict = get_default_dict(section_definition)
    expected_dict = default_dict.copy()
    if isinstance(expected_section_dict, dict):
        expected_dict.update(expected_section_dict)

    section_dict = {}
    for param_key, param in section.params.items():
        if not param_key.startswith("_"):
            section_dict[param_key] = param.value

    remove_ignored_params(section_dict)

    assert_that(section_dict).is_equal_to(expected_dict)


def get_default_dict(section_definition):
    section_key = section_definition.get("key")

    if section_key == "global":
        section_key += "_"

    if "cluster" == section_key:
        section_key += "_sit" if section_definition.get("cluster_model") == ClusterModel.SIT.name else "_hit"

    default_dict = DefaultDict[section_key].value
    return default_dict


def get_mocked_pcluster_config(mocker, auto_refresh=False):
    mocker.patch(
        "pcluster.config.cfn_param_types.get_supported_architectures_for_instance_type", return_value=["x86_64"]
    )
    if "AWS_DEFAULT_REGION" not in os.environ:
        # We need to provide a region to PclusterConfig to avoid no region exception.
        # Which region to provide is arbitrary.
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    pcluster_config = PclusterConfig(config_file="wrong-file", auto_refresh=auto_refresh)
    return pcluster_config


def assert_section_from_file(mocker, section_definition, config_parser_dict, expected_dict_params, expected_message):
    mocker.patch(
        "pcluster.config.cfn_param_types.get_supported_architectures_for_instance_type", return_value=["x86_64"]
    )
    config_parser = configparser.ConfigParser()
    config_parser.read_dict(config_parser_dict)

    # update expected dictionary
    default_dict = get_default_dict(section_definition)
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
            if not param_key.startswith("_"):
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
        param_definition, param_type = get_cfnparam_definition(section.definition, param_key)
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
        param_definition, param_type = get_cfnparam_definition(section_definition, param_key)
        param = param_type(
            section_definition.get("key"),
            "default",
            param_key,
            param_definition,
            pcluster_config,
            owner_section=section,
        )
        param.value = param_value
        section.add_param(param)
    pcluster_config.add_section(section)

    cfn_params = section.to_storage().cfn_params
    if ignore_metadata:
        remove_ignored_params(cfn_params)
        remove_ignored_params(expected_cfn_params)

    assert_that(cfn_params).is_equal_to(expected_cfn_params)


def assert_section_params(mocker, pcluster_config_reader, settings_label, expected_cfn_params):
    mocker.patch(
        "pcluster.config.cfn_param_types.get_supported_architectures_for_instance_type", return_value=["x86_64"]
    )
    mocker.patch(
        "pcluster.utils.InstanceTypeInfo.init_from_instance_type",
        return_value=InstanceTypeInfo(
            {
                "InstanceType": "t2.micro",
                "VCpuInfo": {"DefaultVCpus": 1, "DefaultCores": 1, "DefaultThreadsPerCore": 1},
                "NetworkInfo": {"EfaSupported": False},
            }
        ),
    )
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

        assert_that(len(cfn_params)).is_equal_to(get_cfn_config_num_of_params(pcluster_config))

        remove_ignored_params(cfn_params)

        for param_key, _ in cfn_params.items():
            assert_that(cfn_params.get(param_key), description=param_key).is_equal_to(
                expected_cfn_params.get(param_key)
            )


def init_pcluster_config_from_configparser(config_parser, validate=True, auto_refresh=True):
    with tempfile.NamedTemporaryFile(delete=False) as config_file:

        with open(config_file.name, "w") as cf:
            config_parser.write(cf)

        if "AWS_DEFAULT_REGION" not in os.environ:
            # We need to provide a region to PclusterConfig to avoid no region exception.
            # Which region to provide is arbitrary.
            os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

        pcluster_config = PclusterConfig(
            config_file=config_file.name, cluster_label="default", fail_on_file_absence=True, auto_refresh=auto_refresh
        )
        if validate:
            _validate_config(config_parser, pcluster_config)
    return pcluster_config


def _validate_config(config_parser, pcluster_config):
    """Validate sections and params in config_parser by the order specified in the pcluster_config."""
    for section_key in pcluster_config.get_section_keys():
        for section_label in pcluster_config.get_sections(section_key).keys():
            section_name = section_key + " " + section_label if section_label else section_key
            if section_name in config_parser.sections():
                pcluster_config_section = pcluster_config.get_section(section_key, section_label)
                for validation_func in pcluster_config_section.definition.get("validators", []):
                    errors, warnings = validation_func(section_key, section_label, pcluster_config)
                    if errors:
                        pcluster_config.error(errors)
                    elif warnings:
                        pcluster_config.warn(warnings)
                config_parser_section = OrderedDict(config_parser.items(section_name))
                for param_key in pcluster_config_section.params:
                    if param_key in config_parser_section:
                        pcluster_config_section.get_param(param_key).validate()


def duplicate_config_file(dst_config_file, test_datadir):
    # Make a copy of the src template to the target file.
    # The two resulting PClusterConfig instances will be identical
    src_config_file_path = os.path.join(str(test_datadir), "pcluster.config.ini")
    dst_config_file_path = os.path.join(str(test_datadir), dst_config_file)
    shutil.copy(src_config_file_path, dst_config_file_path)


def get_cfn_config_num_of_params(pcluster_config):
    return (
        CFN_SIT_CONFIG_NUM_OF_PARAMS
        if pcluster_config.cluster_model == ClusterModel.SIT
        else CFN_HIT_CONFIG_NUM_OF_PARAMS
    )


def dict_to_cfn_params(cfn_params_dict):
    """Convert a dictionary to a list of CloudFormation params."""
    if cfn_params_dict:
        cfn_params = []
        for cfn_key, cfn_value in cfn_params_dict.items():
            cfn_params.append({"ParameterKey": cfn_key, "ParameterValue": cfn_value})
    else:
        cfn_params = None
    return cfn_params
