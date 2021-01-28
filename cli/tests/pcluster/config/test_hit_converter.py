# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import configparser
import pytest
from assertpy import assert_that

from pcluster.cluster_model import ClusterModel
from pcluster.config.hit_converter import HitConverter
from pcluster.utils import InstanceTypeInfo
from tests.pcluster.config.utils import init_pcluster_config_from_configparser


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.utils.boto3"


@pytest.mark.parametrize(
    "src_config_dict, dst_config_dict",
    [
        (
            # Scheduler is slurm, conversion expected
            {
                "cluster default": {
                    "scheduler": "slurm",
                    "master_root_volume_size": 30,
                    "compute_root_volume_size": 35,
                    "cluster_type": "ondemand",
                    "enable_efa": "compute",
                    "disable_hyperthreading": True,
                    "placement_group": "DYNAMIC",
                    "compute_instance_type": "t2.micro",
                    "max_queue_size": 10,
                    "spot_price": 0.4,
                    "maintain_initial_size": True,
                    "additional_iam_policies": (
                        "arn:aws:iam::aws:policy/CloudWatchFullAccess,arn:aws:iam::aws:policy/CloudWatchOtherAccess"
                    ),
                    "initial_queue_size": 2,
                    "ebs_settings": "ebs1,ebs2",
                },
                "ebs ebs1": {"shared_dir": "sharedebs", "volume_type": "gp2", "volume_size": 50},
                "ebs ebs2": {"shared_dir": "sharedebs2", "volume_type": "io1", "volume_size": 35},
            },
            {
                "cluster default": {
                    # Common cluster params must be copied
                    "scheduler": "slurm",
                    "master_root_volume_size": 30,
                    "compute_root_volume_size": 35,
                    "enable_efa": None,
                    "additional_iam_policies": [
                        "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
                        "arn:aws:iam::aws:policy/CloudWatchFullAccess",
                        "arn:aws:iam::aws:policy/CloudWatchOtherAccess",
                    ],
                    "disable_hyperthreading": True,
                },
                "queue compute": {
                    "compute_type": "ondemand",
                    "enable_efa": True,
                    "disable_hyperthreading": True,
                    "placement_group": "DYNAMIC",
                    "compute_resource_settings": "default",
                },
                "compute_resource default": {
                    "instance_type": "t2.micro",
                    # maintain_initial_size was False: min_count and initial_count must be set to initial_queue_size
                    "min_count": 2,
                    "max_count": 10,
                    "initial_count": 2,
                    "spot_price": 0.4,
                    "vcpus": 48,
                    "gpus": 0,
                    "enable_efa": True,
                },
                "ebs ebs1": {"shared_dir": "sharedebs", "volume_type": "gp2", "volume_size": 50},
                "ebs ebs2": {"shared_dir": "sharedebs2", "volume_type": "io1", "volume_size": 35},
            },
        ),
        (
            # Scheduler is slurm, conversion expected
            {
                "cluster default": {
                    "scheduler": "slurm",
                    "master_root_volume_size": 35,
                    "compute_root_volume_size": 40,
                    "cluster_type": "ondemand",
                    "disable_hyperthreading": False,
                    "placement_group": "",
                    "compute_instance_type": "t2.micro",
                    "max_queue_size": 10,
                    "spot_price": 0.4,
                    "maintain_initial_size": False,
                    "initial_queue_size": 2,
                }
            },
            {
                "cluster default": {
                    # Common cluster params must be copied
                    "scheduler": "slurm",
                    "master_root_volume_size": 35,
                    "compute_root_volume_size": 40,
                    "enable_efa": None,
                    "disable_hyperthreading": False,
                },
                "queue compute": {
                    "compute_type": "ondemand",
                    "enable_efa": False,
                    "disable_hyperthreading": False,
                    "placement_group": "",
                    "compute_resource_settings": "default",
                },
                "compute_resource default": {
                    "instance_type": "t2.micro",
                    # maintain_initial_size was True: initial_count must be set to initial_queue_size and min_count to 0
                    "min_count": 0,
                    "max_count": 10,
                    "initial_count": 2,
                    "spot_price": 0.4,
                    "vcpus": 96,
                    "gpus": 0,
                    "enable_efa": False,
                },
            },
        ),
        (
            # If scheduler != slurm no conversion must be done
            {
                "cluster default": {
                    "scheduler": "sge",
                    "cluster_type": "ondemand",
                    "enable_efa": "compute",
                    "disable_hyperthreading": True,
                    "placement_group": "DYNAMIC",
                    "compute_instance_type": "t2.micro",
                    "max_queue_size": 10,
                    "spot_price": 0.4,
                    "maintain_initial_size": True,
                    "initial_queue_size": 2,
                }
            },
            {
                "cluster default": {
                    "scheduler": "sge",
                    "cluster_type": "ondemand",
                    "enable_efa": "compute",
                    "disable_hyperthreading": True,
                    "placement_group": "DYNAMIC",
                    "compute_instance_type": "t2.micro",
                    "max_queue_size": 10,
                    "spot_price": 0.4,
                    "maintain_initial_size": True,
                    "initial_queue_size": 2,
                }
            },
        ),
    ],
)
def test_hit_converter(mocker, boto3_stubber, src_config_dict, dst_config_dict):
    scheduler = src_config_dict["cluster default"]["scheduler"]
    instance_type = src_config_dict["cluster default"]["compute_instance_type"]

    mocker.patch(
        "pcluster.config.cfn_param_types.InstanceTypeInfo.init_from_instance_type",
        return_value=InstanceTypeInfo(
            {
                "InstanceType": instance_type,
                "VCpuInfo": {"DefaultVCpus": 96, "DefaultCores": 48, "DefaultThreadsPerCore": 2},
                "NetworkInfo": {"EfaSupported": True, "MaximumNetworkCards": 1},
            }
        ),
    )

    config_parser = configparser.ConfigParser()

    config_parser.read_dict(src_config_dict)
    pcluster_config = init_pcluster_config_from_configparser(config_parser, validate=False)

    HitConverter(pcluster_config).convert()

    if scheduler == "slurm":
        assert_that(pcluster_config.cluster_model).is_equal_to(ClusterModel.HIT)
    else:
        assert_that(pcluster_config.cluster_model).is_equal_to(ClusterModel.SIT)

    for section_key_label, section in dst_config_dict.items():
        section_key, section_label = section_key_label.split(" ")

        src_section = pcluster_config.get_section(section_key, section_label)
        assert_that(src_section).is_not_none()

        for param_key, param_value in section.items():
            assert_that(src_section.get_param_value(param_key)).is_equal_to(param_value)
