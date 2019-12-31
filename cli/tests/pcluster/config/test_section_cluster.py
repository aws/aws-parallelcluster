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
import pytest

import tests.pcluster.config.utils as utils
from pcluster.config.mappings import CLUSTER
from tests.pcluster.config.defaults import DefaultCfnParams, DefaultDict


@pytest.mark.parametrize(
    "cfn_params_dict, expected_section_dict",
    [
        (
            {
                "AccessFrom": "0.0.0.0/0",
                "AdditionalCfnTemplate": "NONE",
                "AdditionalSG": "NONE",
                "AvailabilityZone": "eu-west-1a",
                "BaseOS": "alinux",
                "CLITemplate": "default",
                "ClusterType": "ondemand",
                "ComputeInstanceType": "c4.large",
                "ComputeRootVolumeSize": "15",
                "ComputeSubnetCidr": "NONE",
                "ComputeSubnetId": "subnet-0436191fe84fcff4c",
                "ComputeWaitConditionCount": "1",
                "CustomAMI": "NONE",
                "CustomAWSBatchTemplateURL": "NONE",
                "CustomChefCookbook": "NONE",
                "CustomChefRunList": "NONE",
                "DesiredSize": "1",
                "EBSEncryption": "false, false, false, false, false",
                "EBSKMSKeyId": "NONE, NONE, NONE, NONE, NONE",
                "EBSSnapshotId": "NONE, NONE, NONE, NONE, NONE",
                "EBSVolumeId": "NONE, NONE, NONE, NONE, NONE",
                "EC2IAMRoleName": "NONE",
                "EFSOptions": "NONE, NONE, NONE, NONE, NONE, NONE, NONE, NONE, NONE",
                "EncryptedEphemeral": "false",
                "EphemeralDir": "/scratch",
                "ExtraJson": "{}",
                "KeyName": "test",
                "MasterInstanceType": "c4.large",
                "MasterRootVolumeSize": "15",
                "MasterSubnetId": "subnet-03bfbc8d4e2e3a8f6",
                "MaxSize": "3",
                "MinSize": "1",
                "NumberOfEBSVol": "1",
                "Placement": "cluster",
                "PlacementGroup": "NONE",
                "PostInstallArgs": "NONE",
                "PostInstallScript": "NONE",
                "PreInstallArgs": "NONE",
                "PreInstallScript": "NONE",
                "ProxyServer": "NONE",
                "RAIDOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
                "ResourcesS3Bucket": "NONE",
                "S3ReadResource": "NONE",
                "S3ReadWriteResource": "NONE",
                "ScaleDownIdleTime": "10",
                "Scheduler": "torque",
                "SharedDir": "/shared",
                "SpotPrice": "0.00",
                "Tenancy": "default",
                "UsePublicIps": "true",
                "VPCId": "vpc-004aabeb385513a0d",
                "VPCSecurityGroupId": "NONE",
                "VolumeIOPS": "100, 100, 100, 100, 100",
                "VolumeSize": "20, 20, 20, 20, 20",
                "VolumeType": "gp2, gp2, gp2, gp2, gp2",
                "Cores": "-1,-1",
                "EC2IAMPolicies": "NONE",
                "IntelHPCPlatform": "true",
            },
            utils.merge_dicts(
                DefaultDict["cluster"].value,
                {
                    "key_name": "test",
                    "scheduler": "torque",
                    "master_instance_type": "c4.large",
                    "master_root_volume_size": 15,
                    "compute_instance_type": "c4.large",
                    "compute_root_volume_size": 15,
                    "initial_queue_size": 1,
                    "max_queue_size": 3,
                    "placement": "cluster",
                    "maintain_initial_size": True,
                    "enable_intel_hpc_platform": True,
                    "additional_iam_policies": [],
                },
            ),
        )
    ],
)
def test_cluster_section_from_250_cfn(mocker, cfn_params_dict, expected_section_dict):
    """Test conversion from 2.5.0 CFN input parameters."""
    utils.assert_section_from_cfn(mocker, CLUSTER, cfn_params_dict, expected_section_dict)


@pytest.mark.parametrize(
    "cfn_params_dict, expected_section_dict",
    [
        ({}, utils.merge_dicts(DefaultDict["cluster"].value, {"additional_iam_policies": []})),
        (
            DefaultCfnParams["cluster"].value,
            utils.merge_dicts(
                DefaultDict["cluster"].value,
                {"additional_iam_policies": ["arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"]},
            ),
        ),
        # awsbatch defaults
        (
            utils.merge_dicts(DefaultCfnParams["cluster"].value, {"Scheduler": "awsbatch"}),
            utils.merge_dicts(
                DefaultDict["cluster"].value,
                {
                    "scheduler": "awsbatch",
                    "min_vcpus": 0,
                    "desired_vcpus": 0,
                    "max_vcpus": 10,
                    "spot_bid_percentage": 0.0,
                    # verify also not awsbatch values
                    "initial_queue_size": 0,
                    "max_queue_size": 10,
                    "maintain_initial_size": False,
                    "spot_price": 0,
                    "additional_iam_policies": ["arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"],
                },
            ),
        ),
        # awsbatch custom
        (
            utils.merge_dicts(
                DefaultCfnParams["cluster"].value,
                {"Scheduler": "awsbatch", "MinSize": "2", "DesiredSize": "4", "MaxSize": "8", "SpotPrice": "25"},
            ),
            utils.merge_dicts(
                DefaultDict["cluster"].value,
                {
                    "scheduler": "awsbatch",
                    "min_vcpus": 2,
                    "desired_vcpus": 4,
                    "max_vcpus": 8,
                    "spot_bid_percentage": 25,
                    # verify also not awsbatch values
                    "initial_queue_size": 0,
                    "max_queue_size": 10,
                    "maintain_initial_size": False,
                    "spot_price": 0.0,
                },
            ),
        ),
        # traditional scheduler custom
        (
            utils.merge_dicts(
                DefaultCfnParams["cluster"].value,
                {"Scheduler": "slurm", "MinSize": "2", "DesiredSize": "2", "MaxSize": "8", "SpotPrice": "0.9"},
            ),
            utils.merge_dicts(
                DefaultDict["cluster"].value,
                {
                    "scheduler": "slurm",
                    "initial_queue_size": 2,
                    "max_queue_size": 8,
                    "maintain_initial_size": True,
                    "spot_price": 0.9,
                    # verify also awsbatch values
                    "min_vcpus": 0,
                    "desired_vcpus": 4,
                    "max_vcpus": 10,
                    "spot_bid_percentage": 0,
                },
            ),
        ),
        # single ebs specified through shared_dir only
        (
            utils.merge_dicts(DefaultCfnParams["cluster"].value, {"SharedDir": "test"}),
            utils.merge_dicts(DefaultDict["cluster"].value, {"shared_dir": "test"}),
        ),
        # single ebs specified through ebs setting
        (
            utils.merge_dicts(DefaultCfnParams["cluster"].value, {"SharedDir": "/test,NONE,NONE,NONE,NONE"}),
            utils.merge_dicts(
                DefaultDict["cluster"].value,
                {
                    "shared_dir": "/shared",  # it is the default value, "/test" will be in the ebs section
                    "ebs_settings": "ebs1",
                },
            ),
        ),
        # TODO test all cluster parameters
    ],
)
def test_cluster_section_from_241_cfn(mocker, cfn_params_dict, expected_section_dict):
    """Test conversion from 2.4.1 CFN input parameters."""
    utils.assert_section_from_cfn(mocker, CLUSTER, cfn_params_dict, expected_section_dict)


@pytest.mark.parametrize(
    "cfn_params_dict, expected_section_dict",
    [
        (
            {
                "AccessFrom": "0.0.0.0/0",
                "AdditionalCfnTemplate": "NONE",
                "AdditionalSG": "NONE",
                "AvailabilityZone": "eu-west-1a",
                "BaseOS": "alinux",
                "CLITemplate": "default",
                "ClusterType": "ondemand",
                "ComputeInstanceType": "c4.large",
                "ComputeRootVolumeSize": "15",
                "ComputeSubnetCidr": "NONE",
                "ComputeSubnetId": "subnet-0436191fe84fcff4c",
                "ComputeWaitConditionCount": "1",
                "CustomAMI": "NONE",
                "CustomAWSBatchTemplateURL": "NONE",
                "CustomChefCookbook": "NONE",
                "CustomChefRunList": "NONE",
                "DesiredSize": "1",
                "EBSEncryption": "false, false, false, false, false",
                "EBSKMSKeyId": "NONE, NONE, NONE, NONE, NONE",
                "EBSSnapshotId": "NONE, NONE, NONE, NONE, NONE",
                "EBSVolumeId": "NONE, NONE, NONE, NONE, NONE",
                "EC2IAMRoleName": "NONE",
                "EFSOptions": "NONE, NONE, NONE, NONE, NONE, NONE, NONE, NONE, NONE",
                "EncryptedEphemeral": "false",
                "EphemeralDir": "/scratch",
                "ExtraJson": "{}",
                "KeyName": "test",
                "MasterInstanceType": "c4.large",
                "MasterRootVolumeSize": "15",
                "MasterSubnetId": "subnet-03bfbc8d4e2e3a8f6",
                "MaxSize": "3",
                "MinSize": "1",
                "NumberOfEBSVol": "1",
                "Placement": "cluster",
                "PlacementGroup": "NONE",
                "PostInstallArgs": "NONE",
                "PostInstallScript": "NONE",
                "PreInstallArgs": "NONE",
                "PreInstallScript": "NONE",
                "ProxyServer": "NONE",
                "RAIDOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
                "ResourcesS3Bucket": "NONE",
                "S3ReadResource": "NONE",
                "S3ReadWriteResource": "NONE",
                "ScaleDownIdleTime": "10",
                "Scheduler": "torque",
                "SharedDir": "/shared",
                "SpotPrice": "0.00",
                "Tenancy": "default",
                "UsePublicIps": "true",
                "VPCId": "vpc-004aabeb385513a0d",
                "VPCSecurityGroupId": "NONE",
                "VolumeIOPS": "100, 100, 100, 100, 100",
                "VolumeSize": "20, 20, 20, 20, 20",
                "VolumeType": "gp2, gp2, gp2, gp2, gp2",
            },
            utils.merge_dicts(
                DefaultDict["cluster"].value,
                {
                    "key_name": "test",
                    "scheduler": "torque",
                    "master_instance_type": "c4.large",
                    "master_root_volume_size": 15,
                    "compute_instance_type": "c4.large",
                    "compute_root_volume_size": 15,
                    "initial_queue_size": 1,
                    "max_queue_size": 3,
                    "placement": "cluster",
                    "maintain_initial_size": True,
                    "additional_iam_policies": [],
                },
            ),
        )
    ],
)
def test_cluster_section_from_240_cfn(mocker, cfn_params_dict, expected_section_dict):
    """Test conversion from 2.4.0 CFN input parameters."""
    utils.assert_section_from_cfn(mocker, CLUSTER, cfn_params_dict, expected_section_dict)


@pytest.mark.parametrize(
    "cfn_params_dict, expected_section_dict",
    [
        # 2.3.1 CFN inputs
        (
            {
                "AccessFrom": "0.0.0.0/0",
                "AdditionalCfnTemplate": "NONE",
                "AdditionalSG": "NONE",
                "AvailabilityZone": "eu-west-1a",
                "BaseOS": "centos7",
                "CLITemplate": "default",
                "ClusterType": "ondemand",
                "ComputeInstanceType": "t2.micro",
                "ComputeRootVolumeSize": "250",
                "ComputeSubnetCidr": "NONE",
                "ComputeSubnetId": "subnet-0436191fe84fcff4c",
                "ComputeWaitConditionCount": "2",
                "CustomAMI": "NONE",
                "CustomAWSBatchTemplateURL": "NONE",
                "CustomChefCookbook": "NONE",
                "CustomChefRunList": "NONE",
                "DesiredSize": "2",
                "EBSEncryption": "NONE,NONE,NONE,NONE,NONE",
                "EBSKMSKeyId": "NONE,NONE,NONE,NONE,NONE",
                "EBSSnapshotId": "NONE,NONE,NONE,NONE,NONE",
                "EBSVolumeId": "NONE,NONE,NONE,NONE,NONE",
                "EC2IAMRoleName": "NONE",
                "EFSOptions": "NONE, NONE, NONE, NONE, NONE, NONE, NONE, NONE, NONE",
                "EncryptedEphemeral": "false",
                "EphemeralDir": "/scratch",
                "ExtraJson": "{}",
                "FSXOptions": "NONE, NONE, NONE, NONE, NONE, NONE, NONE, NONE",
                "KeyName": "test",
                "MasterInstanceType": "t2.micro",
                "MasterRootVolumeSize": "250",
                "MasterSubnetId": "subnet-03bfbc8d4e2e3a8f6",
                "MaxSize": "2",
                "MinSize": "0",
                "NumberOfEBSVol": "1",
                "Placement": "compute",
                "PlacementGroup": "NONE",
                "PostInstallArgs": "NONE",
                "PostInstallScript": "NONE",
                "PreInstallArgs": "NONE",
                "PreInstallScript": "NONE",
                "ProxyServer": "NONE",
                "RAIDOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
                "ResourcesS3Bucket": "NONE",
                "S3ReadResource": "NONE",
                "S3ReadWriteResource": "NONE",
                "ScaleDownIdleTime": "10",
                "Scheduler": "slurm",
                "SharedDir": "/shared",
                "SpotPrice": "0.00",
                "Tenancy": "default",
                "UsePublicIps": "true",
                "VPCId": "vpc-004aabeb385513a0d",
                "VPCSecurityGroupId": "NONE",
                "VolumeIOPS": "NONE,NONE,NONE,NONE,NONE",
                "VolumeSize": "20,NONE,NONE,NONE,NONE",
                "VolumeType": "gp2,NONE,NONE,NONE,NONE",
            },
            utils.merge_dicts(
                DefaultDict["cluster"].value,
                {
                    "key_name": "test",
                    "scheduler": "slurm",
                    "master_instance_type": "t2.micro",
                    "master_root_volume_size": 250,
                    "compute_instance_type": "t2.micro",
                    "compute_root_volume_size": 250,
                    "initial_queue_size": 2,
                    "max_queue_size": 2,
                    "placement": "compute",
                    "base_os": "centos7",
                    "additional_iam_policies": [],
                },
            ),
        )
    ],
)
def test_cluster_section_from_231_cfn(mocker, cfn_params_dict, expected_section_dict):
    """Test conversion from 2.3.1 CFN input parameters."""
    utils.assert_section_from_cfn(mocker, CLUSTER, cfn_params_dict, expected_section_dict)


@pytest.mark.parametrize(
    "cfn_params_dict, expected_section_dict",
    [
        (
            {
                "AccessFrom": "0.0.0.0/0",
                "AdditionalCfnTemplate": "NONE",
                "AdditionalSG": "NONE",
                "AvailabilityZone": "eu-west-1a",
                "BaseOS": "ubuntu1404",  # NOTE: ubuntu1404 is no longer supported, but we convert it anyway
                "CLITemplate": "default",
                "ClusterType": "ondemand",
                "ComputeInstanceType": "c4.large",
                "ComputeRootVolumeSize": "15",
                "ComputeSubnetCidr": "NONE",
                "ComputeSubnetId": "subnet-0436191fe84fcff4c",
                "ComputeWaitConditionCount": "0",
                "CustomAMI": "NONE",
                "CustomAWSBatchTemplateURL": "NONE",
                "CustomChefCookbook": "NONE",
                "CustomChefRunList": "NONE",
                "DesiredSize": "0",
                "EBSEncryption": "false, false, false, false, false",
                "EBSKMSKeyId": "NONE, NONE, NONE, NONE, NONE",
                "EBSSnapshotId": "NONE, NONE, NONE, NONE, NONE",
                "EBSVolumeId": "NONE, NONE, NONE, NONE, NONE",
                "EC2IAMRoleName": "NONE",
                "EFSOptions": "NONE, NONE, NONE, NONE, NONE, NONE, NONE, NONE, NONE",
                "EncryptedEphemeral": "false",
                "EphemeralDir": "/scratch",
                "ExtraJson": "{}",
                "KeyName": "test",
                "MasterInstanceType": "c4.large",
                "MasterRootVolumeSize": "15",
                "MasterSubnetId": "subnet-03bfbc8d4e2e3a8f6",
                "MaxSize": "3",
                "MinSize": "0",
                "NumberOfEBSVol": "1",
                "Placement": "cluster",
                "PlacementGroup": "NONE",
                "PostInstallArgs": "NONE",
                "PostInstallScript": "NONE",
                "PreInstallArgs": "NONE",
                "PreInstallScript": "NONE",
                "ProxyServer": "NONE",
                "RAIDOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
                "ResourcesS3Bucket": "NONE",
                "S3ReadResource": "NONE",
                "S3ReadWriteResource": "NONE",
                "ScaleDownIdleTime": "10",
                "Scheduler": "torque",
                "SharedDir": "/shared",
                "SpotPrice": "0.00",
                "Tenancy": "default",
                "UsePublicIps": "true",
                "VPCId": "vpc-004aabeb385513a0d",
                "VPCSecurityGroupId": "NONE",
                "VolumeIOPS": "100, 100, 100, 100, 100",
                "VolumeSize": "20, 20, 20, 20, 20",
                "VolumeType": "gp2, gp2, gp2, gp2, gp2",
            },
            utils.merge_dicts(
                DefaultDict["cluster"].value,
                {
                    "key_name": "test",
                    "scheduler": "torque",
                    "master_instance_type": "c4.large",
                    "master_root_volume_size": 15,
                    "compute_instance_type": "c4.large",
                    "compute_root_volume_size": 15,
                    "initial_queue_size": 0,
                    "max_queue_size": 3,
                    "placement": "cluster",
                    "base_os": "ubuntu1404",  # NOTE: We create the config with the old base_os (no longer supported)
                    "additional_iam_policies": [],
                },
            ),
        )
    ],
)
def test_cluster_section_from_210_cfn(mocker, cfn_params_dict, expected_section_dict):
    """Test conversion from 2.1.0 CFN input parameters."""
    utils.assert_section_from_cfn(mocker, CLUSTER, cfn_params_dict, expected_section_dict)


@pytest.mark.parametrize(
    "cfn_params_dict, expected_section_dict",
    [
        (
            {
                "AccessFrom": "0.0.0.0/0",
                "AdditionalCfnTemplate": "NONE",
                "AdditionalSG": "NONE",
                "AvailabilityZone": "eu-west-1a",
                "BaseOS": "alinux",
                "CLITemplate": "default",
                "ClusterReadyScript": "NONE",
                "ClusterType": "ondemand",
                "ComputeInstanceType": "c4.large",
                "ComputeRootVolumeSize": "15",
                "ComputeSubnetCidr": "NONE",
                "ComputeSubnetId": "subnet-0436191fe84fcff4c",
                "ComputeWaitConditionCount": "2",
                "CustomAMI": "NONE",
                "CustomAWSBatchTemplateURL": "NONE",
                "CustomChefCookbook": "NONE",
                "CustomChefRunList": "NONE",
                "DesiredSize": "0",
                "EBSEncryption": "false, false, false, false, false",
                "EBSKMSKeyId": "NONE, NONE, NONE, NONE, NONE",
                "EBSSnapshotId": "NONE, NONE, NONE, NONE, NONE",
                "EBSVolumeId": "NONE, NONE, NONE, NONE, NONE",
                "EC2IAMRoleName": "NONE",
                "EncryptedEphemeral": "false",
                "EphemeralDir": "/scratch",
                "EphemeralKMSKeyId": "NONE",
                "ExtraJson": "{}",
                "KeyName": "test",
                "MasterInstanceType": "c5.large",
                "MasterRootVolumeSize": "15",
                "MasterSubnetId": "subnet-03bfbc8d4e2e3a8f6",
                "MaxSize": "10",
                "MinSize": "0",
                "NumberOfEBSVol": "1",
                "Placement": "cluster",
                "PlacementGroup": "NONE",
                "PostInstallArgs": "NONE",
                "PostInstallScript": "NONE",
                "PreInstallArgs": "NONE",
                "PreInstallScript": "NONE",
                "ProxyServer": "NONE",
                "ResourcesS3Bucket": "NONE",
                "S3ReadResource": "NONE",
                "S3ReadWriteResource": "NONE",
                "ScaleDownIdleTime": "10",
                "Scheduler": "torque",
                "SharedDir": "/shared",
                "SpotPrice": "0.00",
                "Tenancy": "default",
                "UsePublicIps": "true",
                "VPCId": "vpc-004aabeb385513a0d",
                "VPCSecurityGroupId": "NONE",
                "VolumeIOPS": "100, 100, 100, 100, 100",
                "VolumeSize": "20, 20, 20, 20, 20",
                "VolumeType": "gp2, gp2, gp2, gp2, gp2",
            },
            utils.merge_dicts(
                DefaultDict["cluster"].value,
                {
                    "key_name": "test",
                    "scheduler": "torque",
                    "master_instance_type": "c5.large",
                    "master_root_volume_size": 15,
                    "compute_instance_type": "c4.large",
                    "compute_root_volume_size": 15,
                    "initial_queue_size": 0,
                    "max_queue_size": 10,
                    "placement": "cluster",
                    "additional_iam_policies": [],
                },
            ),
        )
    ],
)
def test_cluster_section_from_200_cfn(mocker, cfn_params_dict, expected_section_dict):
    """Test conversion from 2.0.0 CFN input parameters."""
    utils.assert_section_from_cfn(mocker, CLUSTER, cfn_params_dict, expected_section_dict)


@pytest.mark.parametrize(
    "config_parser_dict, expected_dict_params, expected_message",
    [
        # default
        ({"cluster default": {}}, {"additional_iam_policies": []}, None),
        # right value
        ({"cluster default": {"key_name": "test"}}, {"key_name": "test", "additional_iam_policies": []}, None),
        ({"cluster default": {"base_os": "alinux"}}, {"base_os": "alinux", "additional_iam_policies": []}, None),
        # invalid value
        ({"cluster default": {"base_os": "wrong_value"}}, None, "has an invalid value"),
        # invalid key
        ({"cluster default": {"invalid_key": "fake_value"}}, None, "'invalid_key' is not allowed in the .* section"),
        (
            {"cluster default": {"invalid_key": "fake_value", "invalid_key2": "fake_value"}},
            None,
            "'invalid_key.*,invalid_key.*' are not allowed in the .* section",
        ),
    ],
)
def test_cluster_section_from_file(mocker, config_parser_dict, expected_dict_params, expected_message):
    utils.assert_section_from_file(mocker, CLUSTER, config_parser_dict, expected_dict_params, expected_message)


@pytest.mark.parametrize(
    "param_key, param_value, expected_value, expected_message",
    [
        # Basic configuration
        ("key_name", None, None, None),
        ("key_name", "", None, None),
        ("key_name", "test", "test", None),
        ("key_name", "NONE", "NONE", None),
        ("key_name", "fake_value", "fake_value", None),
        # TODO add regex for template_url
        ("template_url", None, None, None),
        ("template_url", "", None, None),
        ("template_url", "test", "test", None),
        ("template_url", "NONE", "NONE", None),
        ("template_url", "fake_value", "fake_value", None),
        ("base_os", None, "alinux", None),
        ("base_os", "", "alinux", None),
        ("base_os", "wrong_value", None, "has an invalid value"),
        ("base_os", "NONE", None, "has an invalid value"),
        ("base_os", "ubuntu1804", "ubuntu1804", None),
        ("scheduler", None, "sge", None),
        ("scheduler", "", "sge", None),
        ("scheduler", "wrong_value", None, "has an invalid value"),
        ("scheduler", "NONE", None, "has an invalid value"),
        ("scheduler", "awsbatch", "awsbatch", None),
        ("shared_dir", None, "/shared", None),
        ("shared_dir", "", "/shared", None),
        ("shared_dir", "fake_value", "fake_value", None),
        ("shared_dir", "/test", "/test", None),
        ("shared_dir", "/test/test2", "/test/test2", None),
        ("shared_dir", "/t_ 1-2( ):&;<>t?*+|", "/t_ 1-2( ):&;<>t?*+|", None),
        ("shared_dir", "//test", None, "has an invalid value"),
        ("shared_dir", "./test", None, "has an invalid value"),
        ("shared_dir", ".\\test", None, "has an invalid value"),
        ("shared_dir", ".test", None, "has an invalid value"),
        ("shared_dir", "NONE", "NONE", None),  # NONE is evaluated as a valid path
        # Cluster configuration
        ("placement_group", None, None, None),
        ("placement_group", "", None, None),
        ("placement_group", "test", "test", None),
        ("placement_group", "NONE", "NONE", None),
        ("placement_group", "fake_value", "fake_value", None),
        ("placement_group", "DYNAMIC", "DYNAMIC", None),
        ("placement", None, "compute", None),
        ("placement", "", "compute", None),
        ("placement", "wrong_value", None, "has an invalid value"),
        ("placement", "NONE", None, "has an invalid value"),
        ("placement", "cluster", "cluster", None),
        # Master
        # TODO add regex for master_instance_type
        ("master_instance_type", None, "t2.micro", None),
        ("master_instance_type", "", "t2.micro", None),
        ("master_instance_type", "test", "test", None),
        ("master_instance_type", "NONE", "NONE", None),
        ("master_instance_type", "fake_value", "fake_value", None),
        ("master_root_volume_size", None, 25, None),
        ("master_root_volume_size", "", 25, None),
        ("master_root_volume_size", "NONE", None, "must be an Integer"),
        ("master_root_volume_size", "wrong_value", None, "must be an Integer"),
        ("master_root_volume_size", "19", 19, "Allowed values are"),
        ("master_root_volume_size", "22", 22, "Allowed values are"),
        ("master_root_volume_size", "31", 31, None),
        # Compute fleet
        # TODO add regex for compute_instance_type
        ("compute_instance_type", None, "t2.micro", None),
        ("compute_instance_type", "", "t2.micro", None),
        ("compute_instance_type", "test", "test", None),
        ("compute_instance_type", "NONE", "NONE", None),
        ("compute_instance_type", "fake_value", "fake_value", None),
        ("compute_root_volume_size", None, 25, None),
        ("compute_root_volume_size", "", 25, None),
        ("compute_root_volume_size", "NONE", None, "must be an Integer"),
        ("compute_root_volume_size", "wrong_value", None, "must be an Integer"),
        ("compute_root_volume_size", "19", 19, "Allowed values are"),
        ("compute_root_volume_size", "22", 22, "Allowed values are"),
        ("compute_root_volume_size", "31", 31, None),
        ("initial_queue_size", None, 0, None),
        ("initial_queue_size", "", 0, None),
        ("initial_queue_size", "NONE", None, "must be an Integer"),
        ("initial_queue_size", "wrong_value", None, "must be an Integer"),
        ("initial_queue_size", "1", 1, None),
        ("initial_queue_size", "20", 20, None),
        ("max_queue_size", None, 10, None),
        ("max_queue_size", "", 10, None),
        ("max_queue_size", "NONE", None, "must be an Integer"),
        ("max_queue_size", "wrong_value", None, "must be an Integer"),
        ("max_queue_size", "1", 1, None),
        ("max_queue_size", "20", 20, None),
        ("maintain_initial_size", None, False, None),
        ("maintain_initial_size", "", False, None),
        ("maintain_initial_size", "NONE", None, "must be a Boolean"),
        ("maintain_initial_size", "true", True, None),
        ("maintain_initial_size", "false", False, None),
        ("min_vcpus", None, 0, None),
        ("min_vcpus", "", 0, None),
        ("min_vcpus", "NONE", None, "must be an Integer"),
        ("min_vcpus", "wrong_value", None, "must be an Integer"),
        ("min_vcpus", "1", 1, None),
        ("min_vcpus", "20", 20, None),
        ("desired_vcpus", None, 4, None),
        ("desired_vcpus", "", 4, None),
        ("desired_vcpus", "NONE", None, "must be an Integer"),
        ("desired_vcpus", "wrong_value", None, "must be an Integer"),
        ("desired_vcpus", "1", 1, None),
        ("desired_vcpus", "20", 20, None),
        ("max_vcpus", None, 10, None),
        ("max_vcpus", "", 10, None),
        ("max_vcpus", "NONE", None, "must be an Integer"),
        ("max_vcpus", "wrong_value", None, "must be an Integer"),
        ("max_vcpus", "1", 1, None),
        ("max_vcpus", "20", 20, None),
        ("cluster_type", None, "ondemand", None),
        ("cluster_type", "", "ondemand", None),
        ("cluster_type", "wrong_value", None, "has an invalid value"),
        ("cluster_type", "NONE", None, "has an invalid value"),
        ("cluster_type", "spot", "spot", None),
        ("spot_price", None, 0.0, None),
        ("spot_price", "", 0.0, None),
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
        ("spot_bid_percentage", "", 0, None),
        ("spot_bid_percentage", "NONE", None, "must be an Integer"),
        ("spot_bid_percentage", "wrong_value", None, "must be an Integer"),
        ("spot_bid_percentage", "1", 1, None),
        ("spot_bid_percentage", "20", 20, None),
        ("spot_bid_percentage", "100.1", None, "must be an Integer"),
        ("spot_bid_percentage", "101", None, "has an invalid value"),
        # Access and networking
        ("proxy_server", None, None, None),
        ("proxy_server", "", None, None),
        ("proxy_server", "test", "test", None),
        ("proxy_server", "NONE", "NONE", None),
        ("proxy_server", "fake_value", "fake_value", None),
        # TODO add regex for ec2_iam_role
        ("ec2_iam_role", None, None, None),
        ("ec2_iam_role", "", None, None),
        ("ec2_iam_role", "test", "test", None),
        ("ec2_iam_role", "NONE", "NONE", None),
        ("ec2_iam_role", "fake_value", "fake_value", None),
        ("additional_iam_policies", None, [], None),
        ("additional_iam_policies", "", [], None),
        ("additional_iam_policies", "test", ["test"], None),
        ("additional_iam_policies", "NONE", ["NONE"], None),
        ("additional_iam_policies", "fake_value", ["fake_value"], None),
        ("additional_iam_policies", "policy1,policy2", ["policy1", "policy2"], None),
        # TODO add regex for s3_read_resource
        ("s3_read_resource", None, None, None),
        ("s3_read_resource", "", None, None),
        ("s3_read_resource", "fake_value", "fake_value", None),
        ("s3_read_resource", "http://test", "http://test", None),
        ("s3_read_resource", "s3://test/test2", "s3://test/test2", None),
        ("s3_read_resource", "NONE", "NONE", None),
        # TODO add regex for s3_read_write_resource
        ("s3_read_write_resource", None, None, None),
        ("s3_read_write_resource", "", None, None),
        ("s3_read_write_resource", "fake_value", "fake_value", None),
        ("s3_read_write_resource", "http://test", "http://test", None),
        ("s3_read_write_resource", "s3://test/test2", "s3://test/test2", None),
        ("s3_read_write_resource", "NONE", "NONE", None),
        # Customization
        ("enable_efa", None, None, None),
        ("enable_efa", "", None, None),
        ("enable_efa", "wrong_value", None, "has an invalid value"),
        ("enable_efa", "NONE", None, "has an invalid value"),
        ("enable_efa", "compute", "compute", None),
        ("ephemeral_dir", None, "/scratch", None),
        ("ephemeral_dir", "", "/scratch", None),
        ("ephemeral_dir", "fake_value", "fake_value", None),
        ("ephemeral_dir", "/test", "/test", None),
        ("ephemeral_dir", "/test/test2", "/test/test2", None),
        ("ephemeral_dir", "/t_ 1-2( ):&;<>t?*+|", "/t_ 1-2( ):&;<>t?*+|", None),
        ("ephemeral_dir", "//test", None, "has an invalid value"),
        ("ephemeral_dir", "./test", None, "has an invalid value"),
        ("ephemeral_dir", ".\\test", None, "has an invalid value"),
        ("ephemeral_dir", ".test", None, "has an invalid value"),
        ("ephemeral_dir", "NONE", "NONE", None),  # NONE is evaluated as a valid path
        ("encrypted_ephemeral", None, False, None),
        ("encrypted_ephemeral", "", False, None),
        ("encrypted_ephemeral", "NONE", None, "must be a Boolean"),
        ("encrypted_ephemeral", "true", True, None),
        ("encrypted_ephemeral", "false", False, None),
        ("custom_ami", None, None, None),
        ("custom_ami", "", None, None),
        ("custom_ami", "wrong_value", None, "has an invalid value"),
        ("custom_ami", "ami-12345", None, "has an invalid value"),
        ("custom_ami", "ami-123456789", None, "has an invalid value"),
        ("custom_ami", "NONE", None, "has an invalid value"),
        ("custom_ami", "ami-12345678", "ami-12345678", None),
        ("custom_ami", "ami-12345678901234567", "ami-12345678901234567", None),
        # TODO add regex for pre_install
        ("pre_install", None, None, None),
        ("pre_install", "", None, None),
        ("pre_install", "fake_value", "fake_value", None),
        ("pre_install", "http://test", "http://test", None),
        ("pre_install", "s3://test/test2", "s3://test/test2", None),
        ("pre_install", "NONE", "NONE", None),
        ("pre_install_args", None, None, None),
        ("pre_install_args", "", None, None),
        ("pre_install_args", "test", "test", None),
        ("pre_install_args", "NONE", "NONE", None),
        ("pre_install_args", "fake_value", "fake_value", None),
        # TODO add regex for post_install
        ("post_install", None, None, None),
        ("post_install", "", None, None),
        ("post_install", "fake_value", "fake_value", None),
        ("post_install", "http://test", "http://test", None),
        ("post_install", "s3://test/test2", "s3://test/test2", None),
        ("post_install", "NONE", "NONE", None),
        ("post_install_args", None, None, None),
        ("post_install_args", "", None, None),
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
        # TODO add regex for additional_cfn_template
        ("additional_cfn_template", None, None, None),
        ("additional_cfn_template", "", None, None),
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
        ("disable_hyperthreading", "", False, None),
        ("disable_hyperthreading", "NONE", None, "must be a Boolean"),
        ("disable_hyperthreading", "true", True, None),
        ("disable_hyperthreading", "false", False, None),
        ("enable_intel_hpc_platform", None, False, None),
        ("enable_intel_hpc_platform", "", False, None),
        ("enable_intel_hpc_platform", "NONE", None, "must be a Boolean"),
        ("enable_intel_hpc_platform", "true", True, None),
        ("enable_intel_hpc_platform", "false", False, None),
        # TODO add regex for custom_chef_cookbook
        ("custom_chef_cookbook", None, None, None),
        ("custom_chef_cookbook", "", None, None),
        ("custom_chef_cookbook", "fake_value", "fake_value", None),
        ("custom_chef_cookbook", "http://test", "http://test", None),
        ("custom_chef_cookbook", "s3://test/test2", "s3://test/test2", None),
        ("custom_chef_cookbook", "NONE", "NONE", None),
        # TODO add regex for custom_awsbatch_template_url
        ("custom_awsbatch_template_url", None, None, None),
        ("custom_awsbatch_template_url", "", None, None),
        ("custom_awsbatch_template_url", "fake_value", "fake_value", None),
        ("custom_awsbatch_template_url", "http://test", "http://test", None),
        ("custom_awsbatch_template_url", "s3://test/test2", "s3://test/test2", None),
        ("custom_awsbatch_template_url", "NONE", "NONE", None),
        # Settings
        ("scaling_settings", "test1", None, "Section .* not found in the config file"),
        ("scaling_settings", "test1,test2", None, "is invalid. It can only contains a single .* section label"),
        ("vpc_settings", "test1", None, "Section .* not found in the config file"),
        ("vpc_settings", "test1,test2", None, "is invalid. It can only contains a single .* section label"),
        ("vpc_settings", "test1, test2", None, "is invalid. It can only contains a single .* section label"),
        ("ebs_settings", "test1", None, "Section .* not found in the config file"),
        ("ebs_settings", "test1,test2", None, "Section .* not found in the config file"),
        ("ebs_settings", "test1, test2", None, "Section .* not found in the config file"),
        ("efs_settings", "test1", None, "Section .* not found in the config file"),
        ("efs_settings", "test1,test2", None, "is invalid. It can only contains a single .* section label"),
        ("raid_settings", "test1", None, "Section .* not found in the config file"),
        ("raid_settings", "test1,test2", None, "is invalid. It can only contains a single .* section label"),
        ("fsx_settings", "test1", None, "Section .* not found in the config file"),
        ("fsx_settings", "test1,test2", None, "is invalid. It can only contains a single .* section label"),
    ],
)
def test_cluster_param_from_file(mocker, param_key, param_value, expected_value, expected_message):
    utils.assert_param_from_file(mocker, CLUSTER, param_key, param_value, expected_value, expected_message)


@pytest.mark.parametrize(
    "section_definition, section_dict, expected_config_parser_dict, expected_message",
    [
        # default
        (CLUSTER, {}, {"cluster default": {}}, None),
        # default values
        (CLUSTER, {"base_os": "alinux"}, {"cluster default": {"base_os": "alinux"}}, "No option .* in section: .*"),
        # other values
        (CLUSTER, {"key_name": "test"}, {"cluster default": {"key_name": "test"}}, None),
        (CLUSTER, {"base_os": "centos7"}, {"cluster default": {"base_os": "centos7"}}, None),
    ],
)
def test_cluster_section_to_file(
    mocker, section_definition, section_dict, expected_config_parser_dict, expected_message
):
    utils.assert_section_to_file(mocker, CLUSTER, section_dict, expected_config_parser_dict, expected_message)


@pytest.mark.parametrize(
    "section_dict, expected_cfn_params",
    [(DefaultDict["cluster"].value, utils.merge_dicts(DefaultCfnParams["cluster"].value))],
)
def test_cluster_section_to_cfn(mocker, section_dict, expected_cfn_params):
    mocker.patch("pcluster.config.param_types.get_efs_mount_target_id", return_value="valid_mount_target_id")
    mocker.patch("pcluster.config.param_types.get_avail_zone", return_value="mocked_avail_zone")
    utils.assert_section_to_cfn(mocker, CLUSTER, section_dict, expected_cfn_params)


@pytest.mark.parametrize(
    "settings_label, expected_cfn_params",
    [
        ("default", utils.merge_dicts(DefaultCfnParams["cluster"].value)),
        (
            "custom1",
            utils.merge_dicts(
                DefaultCfnParams["cluster"].value,
                {
                    "CLITemplate": "custom1",
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "KeyName": "key",
                    "BaseOS": "ubuntu1804",
                    "Scheduler": "slurm",
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
                    "PreInstallArgs": '"one two"',
                    "PostInstallScript": "postinstall",
                    "PostInstallArgs": '"one two"',
                    "ExtraJson": '{"cfncluster": {"cfn_scheduler_slots": "cores"}}',
                    "AdditionalCfnTemplate": "https://test",
                    "CustomChefCookbook": "https://test",
                    "CustomAWSBatchTemplateURL": "https://test",
                    "Cores": "1,1",
                    "IntelHPCPlatform": "true",
                    # template_url = template
                    # tags = {"test": "test"}
                },
            ),
        ),
        (
            "batch",
            utils.merge_dicts(
                DefaultCfnParams["cluster"].value,
                {
                    "CLITemplate": "batch",
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
                DefaultCfnParams["cluster"].value,
                {
                    "CLITemplate": "batch-custom1",
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
                DefaultCfnParams["cluster"].value,
                {
                    "CLITemplate": "batch-no-cw-logging",
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
                DefaultCfnParams["cluster"].value,
                {
                    "CLITemplate": "wrong_mix_traditional",
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "Scheduler": "slurm",
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
                DefaultCfnParams["cluster"].value,
                {
                    "CLITemplate": "wrong_mix_batch",
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
                DefaultCfnParams["cluster"].value,
                {
                    "CLITemplate": "efs",
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "EFSOptions": "efs,NONE,generalPurpose,NONE,NONE,false,bursting,Valid,NONE",
                },
            ),
        ),
        (
            "dcv",
            utils.merge_dicts(
                DefaultCfnParams["cluster"].value,
                {
                    "CLITemplate": "dcv",
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "DCVOptions": "master,8555,10.0.0.0/0",
                },
            ),
        ),
        (
            "ebs",
            utils.merge_dicts(
                DefaultCfnParams["cluster"].value,
                {
                    "CLITemplate": "ebs",
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "NumberOfEBSVol": "1",
                    "SharedDir": "ebs1,NONE,NONE,NONE,NONE",
                    "VolumeType": "io1,gp2,gp2,gp2,gp2",
                    "VolumeSize": "40,20,20,20,20",
                    "VolumeIOPS": "200,100,100,100,100",
                    "EBSEncryption": "true,false,false,false,false",
                    "EBSKMSKeyId": "kms_key,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "vol-12345678,NONE,NONE,NONE,NONE",
                },
            ),
        ),
        (
            "ebs-multiple",
            utils.merge_dicts(
                DefaultCfnParams["cluster"].value,
                {
                    "CLITemplate": "ebs-multiple",
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "NumberOfEBSVol": "2",
                    "SharedDir": "ebs1,ebs2,NONE,NONE,NONE",
                    "VolumeType": "io1,standard,gp2,gp2,gp2",
                    "VolumeSize": "40,30,20,20,20",
                    "VolumeIOPS": "200,300,100,100,100",
                    "EBSEncryption": "true,false,false,false,false",
                    "EBSKMSKeyId": "kms_key,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "vol-12345678,NONE,NONE,NONE,NONE",
                },
            ),
        ),
        (
            "ebs-shareddir-cluster1",
            utils.merge_dicts(
                DefaultCfnParams["cluster"].value,
                {
                    "CLITemplate": "ebs-shareddir-cluster1",
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "NumberOfEBSVol": "1",
                    "SharedDir": "/shared",
                    "VolumeType": "standard,gp2,gp2,gp2,gp2",
                    "VolumeSize": "30,20,20,20,20",
                    "VolumeIOPS": "300,100,100,100,100",
                    "EBSEncryption": "false,false,false,false,false",
                    "EBSKMSKeyId": "NONE,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "NONE,NONE,NONE,NONE,NONE",
                },
            ),
        ),
        (
            "ebs-shareddir-cluster2",
            utils.merge_dicts(
                DefaultCfnParams["cluster"].value,
                {
                    "CLITemplate": "ebs-shareddir-cluster2",
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "NumberOfEBSVol": "1",
                    "SharedDir": "/work",
                    "VolumeType": "standard,gp2,gp2,gp2,gp2",
                    "VolumeSize": "30,20,20,20,20",
                    "VolumeIOPS": "300,100,100,100,100",
                    "EBSEncryption": "false,false,false,false,false",
                    "EBSKMSKeyId": "NONE,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "NONE,NONE,NONE,NONE,NONE",
                },
            ),
        ),
        (
            "ebs-shareddir-ebs",
            utils.merge_dicts(
                DefaultCfnParams["cluster"].value,
                {
                    "CLITemplate": "ebs-shareddir-ebs",
                    "AvailabilityZone": "mocked_avail_zone",
                    "VPCId": "vpc-12345678",
                    "MasterSubnetId": "subnet-12345678",
                    "NumberOfEBSVol": "1",
                    "SharedDir": "ebs1,NONE,NONE,NONE,NONE",
                    "VolumeType": "io1,gp2,gp2,gp2,gp2",
                    "VolumeSize": "40,20,20,20,20",
                    "VolumeIOPS": "200,100,100,100,100",
                    "EBSEncryption": "true,false,false,false,false",
                    "EBSKMSKeyId": "kms_key,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "vol-12345678,NONE,NONE,NONE,NONE",
                },
            ),
        ),
        (
            "cw_log",
            utils.merge_dicts(DefaultCfnParams["cluster"].value, {"CLITemplate": "cw_log", "CWLogOptions": "true,1"}),
        ),
        (
            "all-settings",
            utils.merge_dicts(
                DefaultCfnParams["cluster"].value,
                {
                    "CLITemplate": "all-settings",
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
                    "VolumeSize": "40,20,20,20,20",
                    "VolumeIOPS": "200,100,100,100,100",
                    "EBSEncryption": "true,false,false,false,false",
                    "EBSKMSKeyId": "kms_key,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "vol-12345678,NONE,NONE,NONE,NONE",
                    # efs
                    "EFSOptions": "efs,NONE,generalPurpose,NONE,NONE,false,bursting,Valid,NONE",
                    # raid
                    "RAIDOptions": "raid,NONE,NONE,gp2,20,100,false,NONE",
                    # fsx
                    "FSXOptions": "fsx,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
                    # dcv
                    "DCVOptions": "master,8555,10.0.0.0/0",
                },
            ),
        ),
        (
            "random-order",
            utils.merge_dicts(
                DefaultCfnParams["cluster"].value,
                {
                    "CLITemplate": "random-order",
                    "AvailabilityZone": "mocked_avail_zone",
                    "KeyName": "key",
                    "BaseOS": "ubuntu1804",
                    "Scheduler": "slurm",
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
                    "PreInstallArgs": '"one two"',
                    "PostInstallScript": "postinstall",
                    "PostInstallArgs": '"one two"',
                    "ExtraJson": '{"cfncluster": {"cfn_scheduler_slots": "cores"}}',
                    "AdditionalCfnTemplate": "https://test",
                    "CustomChefCookbook": "https://test",
                    "CustomAWSBatchTemplateURL": "https://test",
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
                    "VolumeSize": "40,20,20,20,20",
                    "VolumeIOPS": "200,100,100,100,100",
                    "EBSEncryption": "true,false,false,false,false",
                    "EBSKMSKeyId": "kms_key,NONE,NONE,NONE,NONE",
                    "EBSVolumeId": "vol-12345678,NONE,NONE,NONE,NONE",
                    # efs
                    "EFSOptions": "efs,NONE,generalPurpose,NONE,NONE,false,bursting,Valid,NONE",
                    # raid
                    "RAIDOptions": "raid,NONE,NONE,gp2,20,100,false,NONE",
                    # fsx
                    "FSXOptions": "fsx,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
                    # dcv
                    "DCVOptions": "master,8555,10.0.0.0/0",
                },
            ),
        ),
    ],
)
def test_cluster_from_file_to_cfn(mocker, pcluster_config_reader, settings_label, expected_cfn_params):
    """Unit tests for parsing Cluster related options."""
    mocker.patch(
        "pcluster.config.param_types.get_efs_mount_target_id",
        side_effect=lambda efs_fs_id, avail_zone: "master_mt" if avail_zone == "mocked_avail_zone" else None,
    )
    mocker.patch(
        "pcluster.config.param_types.get_avail_zone",
        side_effect=lambda subnet: "mocked_avail_zone" if subnet == "subnet-12345678" else "some_other_az",
    )
    mocker.patch(
        "pcluster.config.validators.get_supported_features",
        return_value={"instances": ["t2.large"], "baseos": ["ubuntu1804"], "schedulers": ["slurm"]},
    )
    mocker.patch("pcluster.config.param_types.get_instance_vcpus", return_value=2)
    utils.assert_section_params(mocker, pcluster_config_reader, settings_label, expected_cfn_params)
