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
import json

import pytest

import tests.pcluster.config.utils as utils
from pcluster.config.mappings import CLUSTER_HIT, CLUSTER_SIT
from tests.pcluster.config.defaults import DefaultCfnParams, DefaultDict


@pytest.mark.parametrize(
    "cfn_params_dict, expected_section_dict, expected_section_label",
    [
        (
            {},
            utils.merge_dicts(DefaultDict["cluster_sit"].value, {"additional_iam_policies": [], "architecture": None}),
            "default",
        ),
        (
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {"ClusterConfigMetadata": "{'sections': {'cluster': ['custom_cluster_label']}}"},
            ),
            # Cluster section with custom label
            utils.merge_dicts(
                DefaultDict["cluster_sit"].value,
                {
                    "additional_iam_policies": ["arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"],
                    "base_os": "alinux2",
                    "scheduler": "slurm",
                    "cluster_config_metadata": {"sections": {"cluster": ["custom_cluster_label"]}},
                    "master_instance_type": "t2.micro",
                    "compute_instance_type": "t2.micro",
                },
            ),
            "custom_cluster_label",
        ),
        (
            DefaultCfnParams["cluster_sit"].value,
            utils.merge_dicts(
                DefaultDict["cluster_sit"].value,
                {
                    "additional_iam_policies": ["arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"],
                    "base_os": "alinux2",
                    "scheduler": "slurm",
                    "master_instance_type": "t2.micro",
                    "compute_instance_type": "t2.micro",
                },
            ),
            "default",
        ),
        # awsbatch defaults
        (
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "Scheduler": "awsbatch",
                    "EC2IAMPolicies": ",".join(
                        [
                            "arn:aws:iam::aws:policy/AWSBatchFullAccess",
                            "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
                        ]
                    ),
                },
            ),
            utils.merge_dicts(
                DefaultDict["cluster_sit"].value,
                {
                    "scheduler": "awsbatch",
                    "base_os": "alinux2",
                    "min_vcpus": 0,
                    "desired_vcpus": 0,
                    "max_vcpus": 10,
                    "spot_bid_percentage": 0.0,
                    # verify also not awsbatch values
                    "initial_queue_size": 0,
                    "max_queue_size": 10,
                    "maintain_initial_size": False,
                    "spot_price": 0,
                    "additional_iam_policies": [
                        "arn:aws:iam::aws:policy/AWSBatchFullAccess",
                        "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
                    ],
                    "master_instance_type": "t2.micro",
                    "compute_instance_type": "t2.micro",
                },
            ),
            "default",
        ),
    ],
)
def test_sit_cluster_section_from_cfn(mocker, cfn_params_dict, expected_section_dict, expected_section_label):
    """Test conversion from CFN input parameters."""
    utils.assert_section_from_cfn(mocker, CLUSTER_SIT, cfn_params_dict, expected_section_dict, expected_section_label)


@pytest.mark.parametrize(
    "config_parser_dict, expected_dict_params, expected_message",
    [
        # default
        (
            {"cluster default": {}},
            {"additional_iam_policies": [], "architecture": None, "scheduler": "slurm", "base_os": "alinux2"},
            None,
        ),
        # right value
        (
            {"cluster default": {"key_name": "test"}},
            {
                "key_name": "test",
                "additional_iam_policies": [],
                "architecture": None,
                "scheduler": "slurm",
                "base_os": "alinux2",
            },
            None,
        ),
        (
            {"cluster default": {"base_os": "alinux"}},
            {"base_os": "alinux", "additional_iam_policies": [], "architecture": None, "scheduler": "slurm"},
            None,
        ),
        # invalid value
        ({"cluster default": {"base_os": "wrong_value"}}, None, "has an invalid value"),
        # invalid key
        ({"cluster default": {"invalid_key": "fake_value"}}, None, "'invalid_key' is not allowed in the .* section"),
        (
            {"cluster default": {"invalid_key": "fake_value", "invalid_key2": "fake_value"}},
            None,
            "'invalid_key.*,invalid_key.*' are not allowed in the .* section",
        ),
        # CLUSTER_HIT parameters must not be allowed in CLUSTER_SIT
        (
            {"cluster default": {"queue_settings": "fake_value"}},
            None,
            "'queue_settings' is not allowed in the .* section",
        ),
        (
            {"cluster default": {"default_queue": "fake_value"}},
            None,
            "'default_queue' is not allowed in the .* section",
        ),
    ],
)
def test_sit_cluster_section_from_file(mocker, config_parser_dict, expected_dict_params, expected_message):
    utils.set_default_values_for_required_cluster_section_params(
        config_parser_dict.get("cluster default"), only_if_not_present=True
    )
    utils.assert_section_from_file(mocker, CLUSTER_SIT, config_parser_dict, expected_dict_params, expected_message)


@pytest.mark.parametrize(
    "config_parser_dict, expected_dict_params, expected_message",
    [
        # default
        (
            {"cluster default": {}},
            {"additional_iam_policies": [], "architecture": None, "scheduler": "slurm", "base_os": "alinux2"},
            None,
        ),
        # right value
        (
            {"cluster default": {"key_name": "test", "disable_cluster_dns": True}},
            {
                "key_name": "test",
                "disable_cluster_dns": True,
                "additional_iam_policies": [],
                "architecture": None,
                "scheduler": "slurm",
                "base_os": "alinux2",
            },
            None,
        ),
        (
            {"cluster default": {"base_os": "alinux"}},
            {"base_os": "alinux", "additional_iam_policies": [], "architecture": None, "scheduler": "slurm"},
            None,
        ),
        # invalid value
        ({"cluster default": {"base_os": "wrong_value"}}, {}, "has an invalid value"),
        # invalid key
        ({"cluster default": {"invalid_key": "fake_value"}}, {}, "'invalid_key' is not allowed in the .* section"),
        # CLUSTER_SIT parameters must not be allowed in CLUSTER_HIT
        (
            {"cluster default": {"placement_group": "fake_value"}},
            {},
            "'placement_group' is not allowed in the .* section",
        ),
        ({"cluster default": {"placement": "ondemand"}}, {}, "'placement' is not allowed in the .* section"),
        (
            {"cluster default": {"compute_instance_type": "t2.micro"}},
            {},
            "'compute_instance_type' is not allowed in the .* section",
        ),
        ({"cluster default": {"initial_queue_size": 0}}, {}, "'initial_queue_size' is not allowed in the .* section"),
        ({"cluster default": {"max_queue_size": 10}}, {}, "'max_queue_size' is not allowed in the .* section"),
        (
            {"cluster default": {"maintain_initial_size": True}},
            {},
            "'maintain_initial_size' is not allowed in the .* section",
        ),
        ({"cluster default": {"cluster_type": "ondemand"}}, {}, "'cluster_type' is not allowed in the .* section"),
        ({"cluster default": {"spot_price": 0}}, {}, "'spot_price' is not allowed in the .* section"),
    ],
)
def test_hit_cluster_section_from_file(mocker, config_parser_dict, expected_dict_params, expected_message):
    config_parser_dict["cluster default"]["queue_settings"] = "queue1"
    config_parser_dict["queue queue1"] = {}
    utils.set_default_values_for_required_cluster_section_params(
        config_parser_dict.get("cluster default"), only_if_not_present=True
    )
    expected_dict_params["queue_settings"] = "queue1"
    utils.assert_section_from_file(mocker, CLUSTER_HIT, config_parser_dict, expected_dict_params, expected_message)


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        # Basic configuration
        ("key_name", None, None, None),
        ("key_name", "", "", None),
        ("key_name", "test", "test", None),
        ("key_name", "NONE", "NONE", None),
        ("key_name", "fake_value", "fake_value", None),
        # TODO add regex for template_url
        ("template_url", None, None, None),
        ("template_url", "", "", None),
        ("template_url", "test", "test", None),
        ("template_url", "NONE", "NONE", None),
        ("template_url", "fake_value", "fake_value", None),
        ("base_os", "", None, "has an invalid value"),
        ("base_os", "wrong_value", None, "has an invalid value"),
        ("base_os", "NONE", None, "has an invalid value"),
        ("base_os", "ubuntu1804", "ubuntu1804", None),
        ("scheduler", "wrong_value", None, "has an invalid value"),
        ("scheduler", "NONE", None, "has an invalid value"),
        ("scheduler", "awsbatch", "awsbatch", None),
        ("shared_dir", None, "/shared", None),
        ("shared_dir", "", None, "has an invalid value"),
        ("shared_dir", "fake_value", "fake_value", None),
        ("shared_dir", "/test", "/test", None),
        ("shared_dir", "/test/test2", "/test/test2", None),
        ("shared_dir", "/t_ 1-2( ):&;<>t?*+|", "/t_ 1-2( ):&;<>t?*+|", None),
        ("shared_dir", "//test", None, "has an invalid value"),
        ("shared_dir", "./test", None, "has an invalid value"),
        ("shared_dir", "\\test", None, "has an invalid value"),
        ("shared_dir", ".test", None, "has an invalid value"),
        ("shared_dir", "/test/.test2", None, "has an invalid value"),
        ("shared_dir", "/test/.test2/test3", None, "has an invalid value"),
        ("shared_dir", "/test//test2", None, "has an invalid value"),
        ("shared_dir", "/test\\test2", None, "has an invalid value"),
        ("shared_dir", "NONE", "NONE", None),  # NONE is evaluated as a valid path
        # Cluster configuration
        ("placement_group", None, None, None),
        ("placement_group", "", "", None),
        ("placement_group", "test", "test", None),
        ("placement_group", "NONE", "NONE", None),
        ("placement_group", "fake_value", "fake_value", None),
        ("placement_group", "DYNAMIC", "DYNAMIC", None),
        ("placement", None, "compute", None),
        ("placement", "", None, "has an invalid value"),
        ("placement", "wrong_value", None, "has an invalid value"),
        ("placement", "NONE", None, "has an invalid value"),
        ("placement", "cluster", "cluster", None),
        # Head node
        # TODO add regex for master_instance_type
        ("master_instance_type", "", "", None),
        ("master_instance_type", "test", "test", None),
        ("master_instance_type", "NONE", "NONE", None),
        ("master_instance_type", "fake_value", "fake_value", None),
        ("master_root_volume_size", None, 25, None),
        ("master_root_volume_size", "", None, "must be an Integer"),
        ("master_root_volume_size", "NONE", None, "must be an Integer"),
        ("master_root_volume_size", "wrong_value", None, "must be an Integer"),
        ("master_root_volume_size", "19", 19, "Allowed values are"),
        ("master_root_volume_size", "22", 22, "Allowed values are"),
        ("master_root_volume_size", "31", 31, None),
        # Compute fleet
        # TODO add regex for compute_instance_type
        ("compute_instance_type", "", "", None),
        ("compute_instance_type", "test", "test", None),
        ("compute_instance_type", "NONE", "NONE", None),
        ("compute_instance_type", "fake_value", "fake_value", None),
        ("compute_root_volume_size", None, 25, None),
        ("compute_root_volume_size", "", None, "must be an Integer"),
        ("compute_root_volume_size", "NONE", None, "must be an Integer"),
        ("compute_root_volume_size", "wrong_value", None, "must be an Integer"),
        ("compute_root_volume_size", "19", 19, "Allowed values are"),
        ("compute_root_volume_size", "22", 22, "Allowed values are"),
        ("compute_root_volume_size", "31", 31, None),
        ("initial_queue_size", None, 0, None),
        ("initial_queue_size", "", None, "must be an Integer"),
        ("initial_queue_size", "NONE", None, "must be an Integer"),
        ("initial_queue_size", "wrong_value", None, "must be an Integer"),
        ("initial_queue_size", "1", 1, None),
        ("initial_queue_size", "20", 20, None),
        ("max_queue_size", None, 10, None),
        ("max_queue_size", "", None, "must be an Integer"),
        ("max_queue_size", "NONE", None, "must be an Integer"),
        ("max_queue_size", "wrong_value", None, "must be an Integer"),
        ("max_queue_size", "1", 1, None),
        ("max_queue_size", "20", 20, None),
        ("maintain_initial_size", None, False, None),
        ("maintain_initial_size", "", None, "must be a Boolean"),
        ("maintain_initial_size", "NONE", None, "must be a Boolean"),
        ("maintain_initial_size", "true", True, None),
        ("maintain_initial_size", "false", False, None),
        ("min_vcpus", None, 0, None),
        ("min_vcpus", "", None, "must be an Integer"),
        ("min_vcpus", "NONE", None, "must be an Integer"),
        ("min_vcpus", "wrong_value", None, "must be an Integer"),
        ("min_vcpus", "1", 1, None),
        ("min_vcpus", "20", 20, None),
        ("desired_vcpus", None, 4, None),
        ("desired_vcpus", "", None, "must be an Integer"),
        ("desired_vcpus", "NONE", None, "must be an Integer"),
        ("desired_vcpus", "wrong_value", None, "must be an Integer"),
        ("desired_vcpus", "1", 1, None),
        ("desired_vcpus", "20", 20, None),
        ("max_vcpus", None, 10, None),
        ("max_vcpus", "", None, "must be an Integer"),
        ("max_vcpus", "NONE", None, "must be an Integer"),
        ("max_vcpus", "wrong_value", None, "must be an Integer"),
        ("max_vcpus", "1", 1, None),
        ("max_vcpus", "20", 20, None),
        ("cluster_type", None, "ondemand", None),
        ("cluster_type", "", None, "has an invalid value"),
        ("cluster_type", "wrong_value", None, "has an invalid value"),
        ("cluster_type", "NONE", None, "has an invalid value"),
        ("cluster_type", "spot", "spot", None),
        ("spot_price", None, 0.0, None),
        ("spot_price", "", None, "must be a Float"),
        ("spot_price", "NONE", None, "must be a Float"),
        ("spot_price", "wrong_value", None, "must be a Float"),
        ("spot_price", "0.09", 0.09, None),
        ("spot_price", "0", 0.0, None),
        ("spot_price", "0.1", 0.1, None),
        ("spot_price", "1", 1, None),
        ("spot_price", "100", 100, None),
        ("spot_price", "100.0", 100.0, None),
        ("spot_price", "100.1", 100.1, None),
        ("spot_price", "101", 101, None),
        ("spot_bid_percentage", None, 0, None),
        ("spot_bid_percentage", "", None, "must be an Integer"),
        ("spot_bid_percentage", "NONE", None, "must be an Integer"),
        ("spot_bid_percentage", "wrong_value", None, "must be an Integer"),
        ("spot_bid_percentage", "1", 1, None),
        ("spot_bid_percentage", "20", 20, None),
        ("spot_bid_percentage", "100.1", None, "must be an Integer"),
        ("spot_bid_percentage", "101", None, "has an invalid value"),
        # Access and networking
        ("proxy_server", None, None, None),
        ("proxy_server", "", "", None),
        ("proxy_server", "test", "test", None),
        ("proxy_server", "NONE", "NONE", None),
        ("proxy_server", "fake_value", "fake_value", None),
        # TODO add regex for ec2_iam_role
        ("ec2_iam_role", None, None, None),
        ("ec2_iam_role", "", "", None),
        ("ec2_iam_role", "test", "test", None),
        ("ec2_iam_role", "NONE", "NONE", None),
        ("ec2_iam_role", "fake_value", "fake_value", None),
        ("additional_iam_policies", None, [], None),
        ("additional_iam_policies", "", [""], None),
        ("additional_iam_policies", "test", ["test"], None),
        ("additional_iam_policies", "NONE", ["NONE"], None),
        ("additional_iam_policies", "fake_value", ["fake_value"], None),
        ("additional_iam_policies", "policy1,policy2", ["policy1", "policy2"], None),
        # TODO add regex for s3_read_resource
        ("s3_read_resource", None, None, None),
        ("s3_read_resource", "", "", None),
        ("s3_read_resource", "fake_value", "fake_value", None),
        ("s3_read_resource", "http://test", "http://test", None),
        ("s3_read_resource", "s3://test/test2", "s3://test/test2", None),
        ("s3_read_resource", "NONE", "NONE", None),
        # TODO add regex for s3_read_write_resource
        ("s3_read_write_resource", None, None, None),
        ("s3_read_write_resource", "", "", None),
        ("s3_read_write_resource", "fake_value", "fake_value", None),
        ("s3_read_write_resource", "http://test", "http://test", None),
        ("s3_read_write_resource", "s3://test/test2", "s3://test/test2", None),
        ("s3_read_write_resource", "NONE", "NONE", None),
        # Customization
        ("enable_efa", None, None, None),
        ("enable_efa", "", None, "has an invalid value"),
        ("enable_efa", "wrong_value", None, "has an invalid value"),
        ("enable_efa", "NONE", None, "has an invalid value"),
        ("enable_efa", "compute", "compute", None),
        ("ephemeral_dir", None, "/scratch", None),
        ("ephemeral_dir", "", None, "has an invalid value"),
        ("ephemeral_dir", "fake_value", "fake_value", None),
        ("ephemeral_dir", "/test", "/test", None),
        ("ephemeral_dir", "/test/test2", "/test/test2", None),
        ("ephemeral_dir", "/t_ 1-2( ):&;<>t?*+|", "/t_ 1-2( ):&;<>t?*+|", None),
        ("ephemeral_dir", "//test", None, "has an invalid value"),
        ("ephemeral_dir", "./test", None, "has an invalid value"),
        ("ephemeral_dir", "\\test", None, "has an invalid value"),
        ("ephemeral_dir", ".test", None, "has an invalid value"),
        ("ephemeral_dir", "/test/.test2", None, "has an invalid value"),
        ("ephemeral_dir", "/test/.test2/test3", None, "has an invalid value"),
        ("ephemeral_dir", "/test//test2", None, "has an invalid value"),
        ("ephemeral_dir", "/test\\test2", None, "has an invalid value"),
        ("ephemeral_dir", "NONE", "NONE", None),  # NONE is evaluated as a valid path
        ("encrypted_ephemeral", None, False, None),
        ("encrypted_ephemeral", "", None, "must be a Boolean"),
        ("encrypted_ephemeral", "NONE", None, "must be a Boolean"),
        ("encrypted_ephemeral", "true", True, None),
        ("encrypted_ephemeral", "false", False, None),
        ("custom_ami", None, None, None),
        ("custom_ami", "", None, "has an invalid value"),
        ("custom_ami", "wrong_value", None, "has an invalid value"),
        ("custom_ami", "ami-12345", None, "has an invalid value"),
        ("custom_ami", "ami-123456789", None, "has an invalid value"),
        ("custom_ami", "NONE", None, "has an invalid value"),
        ("custom_ami", "ami-12345678", "ami-12345678", None),
        ("custom_ami", "ami-12345678901234567", "ami-12345678901234567", None),
        # TODO add regex for pre_install
        ("pre_install", None, None, None),
        ("pre_install", "", "", None),
        ("pre_install", "fake_value", "fake_value", None),
        ("pre_install", "http://test", "http://test", None),
        ("pre_install", "s3://test/test2", "s3://test/test2", None),
        ("pre_install", "NONE", "NONE", None),
        ("pre_install_args", None, None, None),
        ("pre_install_args", "", "", None),
        ("pre_install_args", "test", "test", None),
        ("pre_install_args", "NONE", "NONE", None),
        ("pre_install_args", "fake_value", "fake_value", None),
        # TODO add regex for post_install
        ("post_install", None, None, None),
        ("post_install", "", "", None),
        ("post_install", "fake_value", "fake_value", None),
        ("post_install", "http://test", "http://test", None),
        ("post_install", "s3://test/test2", "s3://test/test2", None),
        ("post_install", "NONE", "NONE", None),
        ("post_install_args", None, None, None),
        ("post_install_args", "", "", None),
        ("post_install_args", "test", "test", None),
        ("post_install_args", "NONE", "NONE", None),
        ("post_install_args", "fake_value", "fake_value", None),
        ("extra_json", None, {}, None),
        ("extra_json", "", {}, None),
        ("extra_json", "{}", {}, None),
        ("extra_json", '{"test": "test"}', {"test": "test"}, None),
        (
            "extra_json",
            "{'test': 'test'}",
            {"test": "test"},
            None,
        ),  # WARNING it is considered a valid value by yaml.safe_load
        ("extra_json", "{'test': 'test'", None, "Error parsing JSON parameter"),
        ("extra_json", "fake_value", "fake_value", None),
        ("cluster_config_metadata", None, {"sections": {}}, None),
        # TODO add regex for additional_cfn_template
        ("additional_cfn_template", None, None, None),
        ("additional_cfn_template", "", "", None),
        ("additional_cfn_template", "fake_value", "fake_value", None),
        ("additional_cfn_template", "http://test", "http://test", None),
        ("additional_cfn_template", "s3://test/test2", "s3://test/test2", None),
        ("additional_cfn_template", "NONE", "NONE", None),
        ("tags", None, {}, None),
        ("tags", "", {}, None),
        ("tags", "{}", {}, None),
        ("tags", "{'test': 'test'}", {"test": "test"}, None),
        ("tags", "{'test': 'test'", None, "Error parsing JSON parameter"),
        ("disable_hyperthreading", None, False, None),
        ("disable_hyperthreading", "", None, "must be a Boolean"),
        ("disable_hyperthreading", "NONE", None, "must be a Boolean"),
        ("disable_hyperthreading", "true", True, None),
        ("disable_hyperthreading", "false", False, None),
        ("enable_intel_hpc_platform", None, False, None),
        ("enable_intel_hpc_platform", "", None, "must be a Boolean"),
        ("enable_intel_hpc_platform", "NONE", None, "must be a Boolean"),
        ("enable_intel_hpc_platform", "true", True, None),
        ("enable_intel_hpc_platform", "false", False, None),
        # TODO add regex for custom_chef_cookbook
        ("custom_chef_cookbook", None, None, None),
        ("custom_chef_cookbook", "", "", None),
        ("custom_chef_cookbook", "fake_value", "fake_value", None),
        ("custom_chef_cookbook", "http://test", "http://test", None),
        ("custom_chef_cookbook", "s3://test/test2", "s3://test/test2", None),
        ("custom_chef_cookbook", "NONE", "NONE", None),
        # Settings
        ("scaling_settings", "test1", None, "Section .* not found in the config file"),
        ("vpc_settings", "test1", None, "Section .* not found in the config file"),
        ("ebs_settings", "test1", None, "Section .* not found in the config file"),
        ("ebs_settings", "test1,test2", None, "Section .* not found in the config file"),
        ("ebs_settings", "test1, test2", None, "Section .* not found in the config file"),
        ("efs_settings", "test1", None, "Section .* not found in the config file"),
        ("raid_settings", "test1", None, "Section .* not found in the config file"),
        ("fsx_settings", "test1", None, "Section .* not found in the config file"),
        ("cw_log_settings", "test1", None, "Section .* not found in the config file"),
        ("dashboard_settings", "test1", None, "Section .* not found in the config file"),
    ],
)
def test_sit_cluster_param_from_file(
    mocker, param_key, param_value, expected_value, expected_message, expected_key_error=None
):
    utils.assert_param_from_file(mocker, CLUSTER_SIT, param_key, param_value, expected_value, expected_message)


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        # Basic configuration
        ("key_name", None, None, None),
        ("key_name", "", "", None),
        ("key_name", "test", "test", None),
        ("key_name", "NONE", "NONE", None),
        ("key_name", "fake_value", "fake_value", None),
        # TODO add regex for template_url
        ("template_url", None, None, None),
        ("template_url", "", "", None),
        ("template_url", "test", "test", None),
        ("template_url", "NONE", "NONE", None),
        ("template_url", "fake_value", "fake_value", None),
        ("base_os", "", None, "has an invalid value"),
        ("base_os", "wrong_value", None, "has an invalid value"),
        ("base_os", "NONE", None, "has an invalid value"),
        ("base_os", "ubuntu1804", "ubuntu1804", None),
        ("scheduler", "wrong_value", None, "has an invalid value"),
        ("scheduler", "NONE", None, "has an invalid value"),
        ("scheduler", "awsbatch", "awsbatch", None),
        ("shared_dir", None, "/shared", None),
        ("shared_dir", "", None, "has an invalid value"),
        ("shared_dir", "fake_value", "fake_value", None),
        ("shared_dir", "/test", "/test", None),
        ("shared_dir", "/test/test2", "/test/test2", None),
        ("shared_dir", "/t_ 1-2( ):&;<>t?*+|", "/t_ 1-2( ):&;<>t?*+|", None),
        ("shared_dir", "//test", None, "has an invalid value"),
        ("shared_dir", "./test", None, "has an invalid value"),
        ("shared_dir", "\\test", None, "has an invalid value"),
        ("shared_dir", ".test", None, "has an invalid value"),
        ("shared_dir", "/test/.test2", None, "has an invalid value"),
        ("shared_dir", "/test/.test2/test3", None, "has an invalid value"),
        ("shared_dir", "/test//test2", None, "has an invalid value"),
        ("shared_dir", "/test\\test2", None, "has an invalid value"),
        ("shared_dir", "NONE", "NONE", None),  # NONE is evaluated as a valid path
        # Head node
        # TODO add regex for master_instance_type
        ("master_instance_type", "", "", None),
        ("master_instance_type", "test", "test", None),
        ("master_instance_type", "NONE", "NONE", None),
        ("master_instance_type", "fake_value", "fake_value", None),
        ("master_root_volume_size", None, 25, None),
        ("master_root_volume_size", "", None, "must be an Integer"),
        ("master_root_volume_size", "NONE", None, "must be an Integer"),
        ("master_root_volume_size", "wrong_value", None, "must be an Integer"),
        ("master_root_volume_size", "19", 19, "Allowed values are"),
        ("master_root_volume_size", "22", 22, "Allowed values are"),
        ("master_root_volume_size", "31", 31, None),
        # Compute fleet
        ("compute_root_volume_size", None, 25, None),
        ("compute_root_volume_size", "", None, "must be an Integer"),
        ("compute_root_volume_size", "NONE", None, "must be an Integer"),
        ("compute_root_volume_size", "wrong_value", None, "must be an Integer"),
        ("compute_root_volume_size", "19", 19, "Allowed values are"),
        ("compute_root_volume_size", "22", 22, "Allowed values are"),
        ("compute_root_volume_size", "31", 31, None),
        # Access and networking
        ("proxy_server", None, None, None),
        ("proxy_server", "", "", None),
        ("proxy_server", "test", "test", None),
        ("proxy_server", "NONE", "NONE", None),
        ("proxy_server", "fake_value", "fake_value", None),
        # TODO add regex for ec2_iam_role
        ("ec2_iam_role", None, None, None),
        ("ec2_iam_role", "", "", None),
        ("ec2_iam_role", "test", "test", None),
        ("ec2_iam_role", "NONE", "NONE", None),
        ("ec2_iam_role", "fake_value", "fake_value", None),
        ("additional_iam_policies", None, [], None),
        ("additional_iam_policies", "", [""], None),
        ("additional_iam_policies", "test", ["test"], None),
        ("additional_iam_policies", "NONE", ["NONE"], None),
        ("additional_iam_policies", "fake_value", ["fake_value"], None),
        ("additional_iam_policies", "policy1,policy2", ["policy1", "policy2"], None),
        # TODO add regex for s3_read_resource
        ("s3_read_resource", None, None, None),
        ("s3_read_resource", "", "", None),
        ("s3_read_resource", "fake_value", "fake_value", None),
        ("s3_read_resource", "http://test", "http://test", None),
        ("s3_read_resource", "s3://test/test2", "s3://test/test2", None),
        ("s3_read_resource", "NONE", "NONE", None),
        # TODO add regex for s3_read_write_resource
        ("s3_read_write_resource", None, None, None),
        ("s3_read_write_resource", "", "", None),
        ("s3_read_write_resource", "fake_value", "fake_value", None),
        ("s3_read_write_resource", "http://test", "http://test", None),
        ("s3_read_write_resource", "s3://test/test2", "s3://test/test2", None),
        ("s3_read_write_resource", "NONE", "NONE", None),
        # Customization
        ("enable_efa", None, None, None),
        ("enable_efa", "", None, "has an invalid value"),
        ("enable_efa", "wrong_value", None, "has an invalid value"),
        ("enable_efa", "NONE", None, "has an invalid value"),
        ("enable_efa", "compute", "compute", None),
        ("ephemeral_dir", None, "/scratch", None),
        ("ephemeral_dir", "", None, "has an invalid value"),
        ("ephemeral_dir", "fake_value", "fake_value", None),
        ("ephemeral_dir", "/test", "/test", None),
        ("ephemeral_dir", "/test/test2", "/test/test2", None),
        ("ephemeral_dir", "/t_ 1-2( ):&;<>t?*+|", "/t_ 1-2( ):&;<>t?*+|", None),
        ("ephemeral_dir", "//test", None, "has an invalid value"),
        ("ephemeral_dir", "./test", None, "has an invalid value"),
        ("ephemeral_dir", "\\test", None, "has an invalid value"),
        ("ephemeral_dir", ".test", None, "has an invalid value"),
        ("ephemeral_dir", "/test/.test2", None, "has an invalid value"),
        ("ephemeral_dir", "/test/.test2/test3", None, "has an invalid value"),
        ("ephemeral_dir", "/test//test2", None, "has an invalid value"),
        ("ephemeral_dir", "/test\\test2", None, "has an invalid value"),
        ("ephemeral_dir", "NONE", "NONE", None),  # NONE is evaluated as a valid path
        ("encrypted_ephemeral", None, False, None),
        ("encrypted_ephemeral", "", None, "must be a Boolean"),
        ("encrypted_ephemeral", "NONE", None, "must be a Boolean"),
        ("encrypted_ephemeral", "true", True, None),
        ("encrypted_ephemeral", "false", False, None),
        ("custom_ami", None, None, None),
        ("custom_ami", "", None, "has an invalid value"),
        ("custom_ami", "wrong_value", None, "has an invalid value"),
        ("custom_ami", "ami-12345", None, "has an invalid value"),
        ("custom_ami", "ami-123456789", None, "has an invalid value"),
        ("custom_ami", "NONE", None, "has an invalid value"),
        ("custom_ami", "ami-12345678", "ami-12345678", None),
        ("custom_ami", "ami-12345678901234567", "ami-12345678901234567", None),
        # TODO add regex for pre_install
        ("pre_install", None, None, None),
        ("pre_install", "", "", None),
        ("pre_install", "fake_value", "fake_value", None),
        ("pre_install", "http://test", "http://test", None),
        ("pre_install", "s3://test/test2", "s3://test/test2", None),
        ("pre_install", "NONE", "NONE", None),
        ("pre_install_args", None, None, None),
        ("pre_install_args", "", "", None),
        ("pre_install_args", "test", "test", None),
        ("pre_install_args", "NONE", "NONE", None),
        ("pre_install_args", "fake_value", "fake_value", None),
        # TODO add regex for post_install
        ("post_install", None, None, None),
        ("post_install", "", "", None),
        ("post_install", "fake_value", "fake_value", None),
        ("post_install", "http://test", "http://test", None),
        ("post_install", "s3://test/test2", "s3://test/test2", None),
        ("post_install", "NONE", "NONE", None),
        ("post_install_args", None, None, None),
        ("post_install_args", "", "", None),
        ("post_install_args", "test", "test", None),
        ("post_install_args", "NONE", "NONE", None),
        ("post_install_args", "fake_value", "fake_value", None),
        ("extra_json", None, {}, None),
        ("extra_json", "", {}, None),
        ("extra_json", "{}", {}, None),
        ("extra_json", '{"test": "test"}', {"test": "test"}, None),
        (
            "extra_json",
            "{'test': 'test'}",
            {"test": "test"},
            None,
        ),  # WARNING it is considered a valid value by yaml.safe_load
        ("extra_json", "{'test': 'test'", None, "Error parsing JSON parameter"),
        ("extra_json", "fake_value", "fake_value", None),
        ("cluster_config_metadata", None, {"sections": {}}, None),
        # TODO add regex for additional_cfn_template
        ("additional_cfn_template", None, None, None),
        ("additional_cfn_template", "", "", None),
        ("additional_cfn_template", "fake_value", "fake_value", None),
        ("additional_cfn_template", "http://test", "http://test", None),
        ("additional_cfn_template", "s3://test/test2", "s3://test/test2", None),
        ("additional_cfn_template", "NONE", "NONE", None),
        ("tags", None, {}, None),
        ("tags", "", {}, None),
        ("tags", "{}", {}, None),
        ("tags", "{'test': 'test'}", {"test": "test"}, None),
        ("tags", "{'test': 'test'", None, "Error parsing JSON parameter"),
        ("enable_intel_hpc_platform", None, False, None),
        ("enable_intel_hpc_platform", "", None, "must be a Boolean"),
        ("enable_intel_hpc_platform", "NONE", None, "must be a Boolean"),
        ("enable_intel_hpc_platform", "true", True, None),
        ("enable_intel_hpc_platform", "false", False, None),
        # TODO add regex for custom_chef_cookbook
        ("custom_chef_cookbook", None, None, None),
        ("custom_chef_cookbook", "", "", None),
        ("custom_chef_cookbook", "fake_value", "fake_value", None),
        ("custom_chef_cookbook", "http://test", "http://test", None),
        ("custom_chef_cookbook", "s3://test/test2", "s3://test/test2", None),
        ("custom_chef_cookbook", "NONE", "NONE", None),
        # Settings
        ("scaling_settings", "test1", None, "Section .* not found in the config file"),
        ("vpc_settings", "test1", None, "Section .* not found in the config file"),
        ("ebs_settings", "test1", None, "Section .* not found in the config file"),
        ("ebs_settings", "test1,test2", None, "Section .* not found in the config file"),
        ("ebs_settings", "test1, test2", None, "Section .* not found in the config file"),
        ("efs_settings", "test1", None, "Section .* not found in the config file"),
        ("raid_settings", "test1", None, "Section .* not found in the config file"),
        ("fsx_settings", "test1", None, "Section .* not found in the config file"),
        ("cw_log_settings", "test1", None, "Section .* not found in the config file"),
        ("dashboard_settings", "test1", None, "Section .* not found in the config file"),
    ],
)
def test_hit_cluster_param_from_file(
    mocker, param_key, param_value, expected_value, expected_message, expected_key_error=None
):
    utils.assert_param_from_file(mocker, CLUSTER_HIT, param_key, param_value, expected_value, expected_message)


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        ("scheduler", None, None, "Configuration parameter 'scheduler' must have a value"),
        ("base_os", None, None, "Configuration parameter 'base_os' must have a value"),
        ("key_name", None, None, "Configuration parameter 'key_name' must have a value"),
    ],
)
def test_sit_cluster_param_from_file_with_validation(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(
        mocker, CLUSTER_SIT, param_key, param_value, expected_value, expected_message, do_validation=True
    )


@pytest.mark.parametrize(
    "section_dict, expected_config_parser_dict, expected_message",
    [
        # default
        ({}, {"cluster default": {}}, None),
        # default values
        ({"placement": "compute"}, {"cluster default": {"placement": "compute"}}, "No option .* in section: .*"),
        # other values
        ({"key_name": "test"}, {"cluster default": {"key_name": "test"}}, None),
        ({"base_os": "centos7"}, {"cluster default": {"base_os": "centos7"}}, None),
    ],
)
def test_sit_cluster_section_to_file(mocker, section_dict, expected_config_parser_dict, expected_message):
    utils.assert_section_to_file(mocker, CLUSTER_SIT, section_dict, expected_config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "cluster_section_definition, section_dict, expected_cfn_params, default_threads_per_core",
    [
        (CLUSTER_SIT, DefaultDict["cluster_sit"].value, DefaultCfnParams["cluster_sit"].value, (1, 1)),
        (CLUSTER_HIT, DefaultDict["cluster_hit"].value, DefaultCfnParams["cluster_hit"].value, (1, 1)),
        (
            CLUSTER_SIT,
            utils.merge_dicts(DefaultDict["cluster_sit"].value, {"disable_hyperthreading": "True"}),
            utils.merge_dicts(DefaultCfnParams["cluster_sit"].value, {"Cores": "2,2,true,true"}),
            (2, 2),
        ),
        (
            CLUSTER_SIT,
            utils.merge_dicts(DefaultDict["cluster_sit"].value, {"disable_hyperthreading": "True"}),
            utils.merge_dicts(DefaultCfnParams["cluster_sit"].value, {"Cores": "NONE,NONE,false,false"}),
            (1, 1),
        ),
        (
            CLUSTER_SIT,
            utils.merge_dicts(DefaultDict["cluster_sit"].value, {"disable_hyperthreading": "True"}),
            utils.merge_dicts(DefaultCfnParams["cluster_sit"].value, {"Cores": "2,NONE,true,false"}),
            (2, 1),
        ),
        (
            CLUSTER_SIT,
            utils.merge_dicts(DefaultDict["cluster_sit"].value, {"disable_hyperthreading": "True"}),
            utils.merge_dicts(DefaultCfnParams["cluster_sit"].value, {"Cores": "NONE,2,false,true"}),
            (1, 2),
        ),
        (
            CLUSTER_HIT,
            utils.merge_dicts(DefaultDict["cluster_hit"].value, {"disable_hyperthreading": "True"}),
            # With HIT clusters there should be no cores information for compute instance type
            utils.merge_dicts(DefaultCfnParams["cluster_hit"].value, {"Cores": "2,0,true,false"}),
            (2, 2),
        ),
        (
            CLUSTER_HIT,
            utils.merge_dicts(DefaultDict["cluster_hit"].value, {"disable_hyperthreading": "True"}),
            # With HIT clusters there should be no cores information for compute instance type
            utils.merge_dicts(DefaultCfnParams["cluster_hit"].value, {"Cores": "NONE,0,false,false"}),
            (1, 1),
        ),
        (
            CLUSTER_HIT,
            utils.merge_dicts(DefaultDict["cluster_hit"].value, {"disable_hyperthreading": "True"}),
            # With HIT clusters there should be no cores information for compute instance type
            utils.merge_dicts(DefaultCfnParams["cluster_hit"].value, {"Cores": "2,0,true,false"}),
            (2, 1),
        ),
        (
            CLUSTER_HIT,
            utils.merge_dicts(DefaultDict["cluster_hit"].value, {"disable_hyperthreading": "True"}),
            # With HIT clusters there should be no cores information for compute instance type
            utils.merge_dicts(DefaultCfnParams["cluster_hit"].value, {"Cores": "NONE,0,false,false"}),
            (1, 2),
        ),
    ],
)
def test_cluster_section_to_cfn(
    mocker, cluster_section_definition, section_dict, expected_cfn_params, default_threads_per_core
):
    section_dict["master_instance_type"] = "t2.micro"
    if cluster_section_definition == CLUSTER_SIT:
        section_dict["compute_instance_type"] = "t2.micro"
    utils.set_default_values_for_required_cluster_section_params(section_dict)
    utils.mock_pcluster_config(mocker)
    mocker.patch("pcluster.config.cfn_param_types.get_efs_mount_target_id", return_value="valid_mount_target_id")
    instance_type_info_mock = mocker.MagicMock()
    mocker.patch(
        "pcluster.config.cfn_param_types.InstanceTypeInfo.init_from_instance_type", return_value=instance_type_info_mock
    )
    instance_type_info_mock.vcpus_count.return_value = 4
    instance_type_info_mock.default_threads_per_core.side_effect = default_threads_per_core
    utils.assert_section_to_cfn(mocker, cluster_section_definition, section_dict, expected_cfn_params)


@pytest.mark.parametrize(
    "settings_label, expected_cfn_params",
    [
        ("default", utils.merge_dicts(DefaultCfnParams["cluster_sit"].value, {"Scheduler": "sge"})),
        (
            "custom1",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "KeyName": "key",
                    "BaseOS": "ubuntu1804",
                    "Scheduler": "sge",
                    "SharedDir": "/test",
                    "PlacementGroup": "NONE",
                    "Placement": "cluster",
                    "MasterInstanceType": "t2.large",
                    "MasterRootVolumeSize": "30",
                    "ComputeInstanceType": "t2.large",
                    "ComputeRootVolumeSize": "30",
                    "DesiredSize": "1",
                    "MaxSize": "2",
                    "MinSize": "1",
                    "ClusterType": "spot",
                    "SpotPrice": "5.5",
                    "ProxyServer": "proxy",
                    "EC2IAMRoleName": "role",
                    "EC2IAMPolicies": "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy,policy1,policy2",
                    "S3ReadResource": "s3://url",
                    "S3ReadWriteResource": "s3://url",
                    "EFA": "compute",
                    "EphemeralDir": "/test2",
                    "EncryptedEphemeral": "true",
                    "CustomAMI": "ami-12345678",
                    "PreInstallScript": "preinstall",
                    "PreInstallArgs": '\\"one two\\"',
                    "PostInstallScript": "postinstall",
                    "PostInstallArgs": '\\"one two\\"',
                    "ExtraJson": '{"cfncluster": {"cfn_scheduler_slots": "cores"}}',
                    "AdditionalCfnTemplate": "https://test",
                    "CustomChefCookbook": "https://test",
                    "Cores": "NONE,NONE,false,false",
                    "IntelHPCPlatform": "true",
                    # template_url = template
                    # tags = {"test": "test"}
                },
            ),
        ),
        (
            "batch",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "Scheduler": "awsbatch",
                    "DesiredSize": "4",
                    "MaxSize": "10",
                    "MinSize": "0",
                    "SpotPrice": "0",
                    "EC2IAMPolicies": ",".join(
                        [
                            "arn:aws:iam::aws:policy/AWSBatchFullAccess",
                            "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
                        ]
                    ),
                    "ComputeInstanceType": "optimal",
                },
            ),
        ),
        (
            "batch-custom1",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "Scheduler": "awsbatch",
                    "DesiredSize": "3",
                    "MaxSize": "4",
                    "MinSize": "2",
                    "ClusterType": "spot",
                    "SpotPrice": "25",
                    "EC2IAMPolicies": ",".join(
                        [
                            "arn:aws:iam::aws:policy/AWSBatchFullAccess",
                            "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
                            "policy1",
                            "policy2",
                        ]
                    ),
                    "ComputeInstanceType": "optimal",
                },
            ),
        ),
        (
            "batch-no-cw-logging",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "Scheduler": "awsbatch",
                    "DesiredSize": "3",
                    "MaxSize": "4",
                    "MinSize": "2",
                    "ClusterType": "spot",
                    "SpotPrice": "25",
                    "EC2IAMPolicies": "arn:aws:iam::aws:policy/AWSBatchFullAccess",
                    "ComputeInstanceType": "optimal",
                    "CWLogOptions": "false,14",
                },
            ),
        ),
        (
            "wrong_mix_traditional",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "Scheduler": "sge",
                    "DesiredSize": "1",
                    "MaxSize": "2",
                    "MinSize": "1",
                    "ClusterType": "spot",
                    "SpotPrice": "5.5",
                },
            ),
        ),
        (
            "wrong_mix_batch",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "Scheduler": "awsbatch",
                    "DesiredSize": "3",
                    "MaxSize": "4",
                    "MinSize": "2",
                    "ClusterType": "spot",
                    "SpotPrice": "25",
                    "EC2IAMPolicies": ",".join(
                        [
                            "arn:aws:iam::aws:policy/AWSBatchFullAccess",
                            "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
                        ]
                    ),
                    "ComputeInstanceType": "optimal",
                },
            ),
        ),
        (
            "efs",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "EFSOptions": "efs,NONE,generalPurpose,NONE,NONE,false,bursting,Valid,NONE",
                    "Scheduler": "sge",
                },
            ),
        ),
        (
            "dcv",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "DCVOptions": "master,8555,10.0.0.0/0",
                    "Scheduler": "sge",
                },
            ),
        ),
        (
            "ebs",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "NumberOfEBSVol": "1",
                    "SharedDir": "ebs1,NONE,NONE,NONE,NONE",
                    "VolumeType": "io1,gp2,gp2,gp2,gp2",
                    "VolumeSize": "40,NONE,NONE,NONE,NONE",
                    "VolumeIOPS": "200,NONE,NONE,NONE,NONE",
                    "EBSEncryption": "true,false,false,false,false",
                    "EBSKMSKeyId": "kms_key,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "vol-12345678,NONE,NONE,NONE,NONE",
                    "Scheduler": "sge",
                },
            ),
        ),
        (
            "ebs-multiple",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "NumberOfEBSVol": "2",
                    "SharedDir": "ebs1,ebs2,NONE,NONE,NONE",
                    "VolumeType": "io1,standard,gp2,gp2,gp2",
                    "VolumeSize": "40,30,NONE,NONE,NONE",
                    "VolumeIOPS": "200,300,NONE,NONE,NONE",
                    "EBSEncryption": "true,false,false,false,false",
                    "EBSKMSKeyId": "kms_key,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "vol-12345678,NONE,NONE,NONE,NONE",
                    "Scheduler": "sge",
                },
            ),
        ),
        (
            "ebs-shareddir-cluster1",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "NumberOfEBSVol": "1",
                    "SharedDir": "/shared",
                    "VolumeType": "standard,gp2,gp2,gp2,gp2",
                    "VolumeSize": "30,NONE,NONE,NONE,NONE",
                    "VolumeIOPS": "300,NONE,NONE,NONE,NONE",
                    "EBSEncryption": "false,false,false,false,false",
                    "EBSKMSKeyId": "NONE,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "NONE,NONE,NONE,NONE,NONE",
                    "Scheduler": "sge",
                },
            ),
        ),
        (
            "ebs-shareddir-cluster2",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "NumberOfEBSVol": "1",
                    "SharedDir": "/work",
                    "VolumeType": "standard,gp2,gp2,gp2,gp2",
                    "VolumeSize": "30,NONE,NONE,NONE,NONE",
                    "VolumeIOPS": "300,NONE,NONE,NONE,NONE",
                    "EBSEncryption": "false,false,false,false,false",
                    "EBSKMSKeyId": "NONE,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "NONE,NONE,NONE,NONE,NONE",
                    "Scheduler": "sge",
                },
            ),
        ),
        (
            "ebs-shareddir-ebs",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "NumberOfEBSVol": "1",
                    "SharedDir": "ebs1,NONE,NONE,NONE,NONE",
                    "VolumeType": "io1,gp2,gp2,gp2,gp2",
                    "VolumeSize": "40,NONE,NONE,NONE,NONE",
                    "VolumeIOPS": "200,NONE,NONE,NONE,NONE",
                    "EBSEncryption": "true,false,false,false,false",
                    "EBSKMSKeyId": "kms_key,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "vol-12345678,NONE,NONE,NONE,NONE",
                    "Scheduler": "sge",
                },
            ),
        ),
        (
            "cw_log",
            utils.merge_dicts(DefaultCfnParams["cluster_sit"].value, {"CWLogOptions": "true,1", "Scheduler": "sge"}),
        ),
        (
            "all-settings",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "AvailabilityZone": "mocked_avail_zone",
                    # scaling
                    "ScaleDownIdleTime": "15",
                    # vpc
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    # ebs
                    "NumberOfEBSVol": "1",
                    "SharedDir": "ebs1,NONE,NONE,NONE,NONE",
                    "VolumeType": "io1,gp2,gp2,gp2,gp2",
                    "VolumeSize": "40,NONE,NONE,NONE,NONE",
                    "VolumeIOPS": "200,NONE,NONE,NONE,NONE",
                    "EBSEncryption": "true,false,false,false,false",
                    "EBSKMSKeyId": "kms_key,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "vol-12345678,NONE,NONE,NONE,NONE",
                    # efs
                    "EFSOptions": "efs,NONE,generalPurpose,NONE,NONE,false,bursting,Valid,NONE",
                    # raid
                    "RAIDOptions": "raid,NONE,2,gp2,20,NONE,false,NONE,125",
                    # fsx
                    "FSXOptions": "fsx,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,"
                    "NONE,NONE",
                    # dcv
                    "DCVOptions": "master,8555,10.0.0.0/0",
                    "Scheduler": "sge",
                },
            ),
        ),
        (
            "random-order",
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "AvailabilityZone": "mocked_avail_zone",
                    "KeyName": "key",
                    "BaseOS": "ubuntu1804",
                    "Scheduler": "sge",
                    # "SharedDir": "/test",  # we have ebs volumes, see below
                    "PlacementGroup": "NONE",
                    "Placement": "cluster",
                    "MasterInstanceType": "t2.large",
                    "MasterRootVolumeSize": "30",
                    "ComputeInstanceType": "t2.large",
                    "ComputeRootVolumeSize": "30",
                    "DesiredSize": "1",
                    "MaxSize": "2",
                    "MinSize": "1",
                    "ClusterType": "spot",
                    "SpotPrice": "5.5",
                    "ProxyServer": "proxy",
                    "EC2IAMRoleName": "role",
                    "S3ReadResource": "s3://url",
                    "S3ReadWriteResource": "s3://url",
                    "EFA": "compute",
                    "EphemeralDir": "/test2",
                    "EncryptedEphemeral": "true",
                    "CustomAMI": "ami-12345678",
                    "PreInstallScript": "preinstall",
                    "PreInstallArgs": '\\"one two\\"',
                    "PostInstallScript": "postinstall",
                    "PostInstallArgs": '\\"one two\\"',
                    "ExtraJson": '{"cfncluster": {"cfn_scheduler_slots": "cores"}}',
                    "AdditionalCfnTemplate": "https://test",
                    "CustomChefCookbook": "https://test",
                    "IntelHPCPlatform": "false",
                    # scaling
                    "ScaleDownIdleTime": "15",
                    # vpc
                    "VPCId": "vpc-12345678",
                    #
                    "MasterSubnetId": "subnet-12345678",
                    "ComputeSubnetId": "subnet-23456789",
                    # ebs
                    "NumberOfEBSVol": "1",
                    "SharedDir": "ebs1,NONE,NONE,NONE,NONE",
                    "VolumeType": "io1,gp2,gp2,gp2,gp2",
                    "VolumeSize": "40,NONE,NONE,NONE,NONE",
                    "VolumeIOPS": "200,NONE,NONE,NONE,NONE",
                    "EBSEncryption": "true,false,false,false,false",
                    "EBSKMSKeyId": "kms_key,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "vol-12345678,NONE,NONE,NONE,NONE",
                    # efs
                    "EFSOptions": "efs,NONE,generalPurpose,NONE,NONE,false,bursting,Valid,NONE",
                    # raid
                    "RAIDOptions": "raid,NONE,2,gp2,20,NONE,false,NONE,125",
                    # fsx
                    "FSXOptions": "fsx,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,"
                    "NONE,NONE",
                    # dcv
                    "DCVOptions": "master,8555,10.0.0.0/0",
                },
            ),
        ),
    ],
)
def test_sit_cluster_from_file_to_cfn(mocker, pcluster_config_reader, settings_label, expected_cfn_params):
    """Unit tests for parsing Cluster related options."""
    mocker.patch(
        "pcluster.config.cfn_param_types.get_efs_mount_target_id",
        side_effect=lambda efs_fs_id, avail_zone: "master_mt" if avail_zone == "mocked_avail_zone" else None,
    )
    mocker.patch(
        "pcluster.config.cfn_param_types.get_availability_zone_of_subnet",
        side_effect=lambda subnet: "mocked_avail_zone" if subnet == "subnet-12345678" else "some_other_az",
    )

    mocker.patch("pcluster.config.cfn_param_types.InstanceTypeInfo.vcpus_count", return_value=2)
    utils.assert_section_params(mocker, pcluster_config_reader, settings_label, expected_cfn_params)


@pytest.mark.parametrize(
    "section_dict, expected_cfn_params",
    [
        (
            DefaultDict["cluster_sit"].value,
            utils.merge_dicts(
                DefaultCfnParams["cluster_sit"].value,
                {
                    "ClusterConfigMetadata": json.dumps(
                        {"sections": {"scaling": ["default"], "vpc": ["default"], "cluster": ["default"]}},
                        sort_keys=True,
                    )
                },
            ),
        )
    ],
)
def test_sit_cluster_config_metadata_to_cfn(mocker, section_dict, expected_cfn_params):
    utils.mock_pcluster_config(mocker)
    mocker.patch("pcluster.config.cfn_param_types.get_efs_mount_target_id", return_value="valid_mount_target_id")
    utils.assert_section_to_cfn(mocker, CLUSTER_SIT, section_dict, expected_cfn_params, ignore_metadata=False)
