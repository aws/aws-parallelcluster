import hashlib
import importlib.util
import sys
from unittest.mock import patch

import pytest
from cfnlint.__main__ import main as cfnlint
from jinja2 import Environment, FileSystemLoader

spec = importlib.util.spec_from_file_location("cfn_formatter", "../utils/cfn_formatter.py")
cfn_formatter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cfn_formatter)


def substack_rendering(tmp_path, template_name, test_config):

    env = Environment(loader=FileSystemLoader(".."))
    env.filters["sha1"] = lambda value: hashlib.sha1(value.strip().encode()).hexdigest()
    template = env.get_template(template_name)
    output_from_parsed_template = template.render(config=test_config, config_version="version")
    rendered_file = tmp_path / template_name
    rendered_file.write_text(output_from_parsed_template)

    # Run cfn-lint
    cfn_lint_args = ["--info", str(rendered_file)]  # TODO "-i", "W2001" could be added to ignore unused vars
    with patch.object(sys, "argv", cfn_lint_args):
        assert cfnlint() == 0

    # Run format check
    assert cfn_formatter.check_formatting([str(rendered_file)], "yaml")


@pytest.mark.parametrize(
    "test_config",
    [
        (
            {
                "cluster": {
                    "label": "default",
                    "default_queue": "multiple_spot",
                    "queue_settings": {
                        "multiple_spot": {
                            "compute_type": "spot",
                            "enable_efa": False,
                            "disable_hyperthreading": True,
                            "placement_group": None,
                            "compute_resource_settings": {
                                "multiple_spot_c4.xlarge": {
                                    "instance_type": "c4.xlarge",
                                    "min_count": 0,
                                    "max_count": 10,
                                    "spot_price": None,
                                    "vcpus": 2,
                                    "gpus": 0,
                                    "enable_efa": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": False,
                                },
                                "multiple_spot_c5.2xlarge": {
                                    "instance_type": "c5.2xlarge",
                                    "min_count": 1,
                                    "max_count": 5,
                                    "spot_price": 1.5,
                                    "vcpus": 4,
                                    "gpus": 0,
                                    "enable_efa": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": True,
                                },
                            },
                        },
                        "efa": {
                            "compute_resource_settings": {
                                "efa_c5n.18xlarge": {
                                    "instance_type": "c5n.18xlarge",
                                    "min_count": 0,
                                    "max_count": 5,
                                    "spot_price": None,
                                    "vcpus": 36,
                                    "gpus": 0,
                                    "enable_efa": True,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": True,
                                }
                            },
                            "compute_type": "ondemand",
                            "enable_efa": True,
                            "disable_hyperthreading": True,
                            "placement_group": "DYNAMIC",
                        },
                        "gpu": {
                            "compute_resource_settings": {
                                "gpu_g3.8xlarge": {
                                    "instance_type": "g3.8xlarge",
                                    "min_count": 0,
                                    "max_count": 5,
                                    "spot_price": None,
                                    "vcpus": 16,
                                    "gpus": 2,
                                    "enable_efa": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": True,
                                }
                            },
                            "compute_type": "ondemand",
                            "enable_efa": False,
                            "disable_hyperthreading": True,
                            "placement_group": None,
                        },
                    },
                    "scaling": {"scaledown_idletime": 10},
                    "disable_cluster_dns": False,
                }
            }
        ),
        (
            {
                "cluster": {
                    "label": "default",
                    "default_queue": "multiple_spot",
                    "queue_settings": {
                        "multiple_spot": {
                            "compute_type": "spot",
                            "enable_efa": False,
                            "disable_hyperthreading": True,
                            "placement_group": None,
                            "compute_resource_settings": {
                                "multiple_spot_c4.xlarge": {
                                    "instance_type": "c4.xlarge",
                                    "min_count": 0,
                                    "max_count": 10,
                                    "spot_price": None,
                                    "vcpus": 2,
                                    "gpus": 0,
                                    "enable_efa": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": True,
                                },
                                "multiple_spot_c5.2xlarge": {
                                    "instance_type": "c5.2xlarge",
                                    "min_count": 1,
                                    "max_count": 5,
                                    "spot_price": 1.5,
                                    "vcpus": 4,
                                    "gpus": 0,
                                    "enable_efa": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": True,
                                },
                            },
                        }
                    },
                    "scaling": {"scaledown_idletime": 10},
                    "disable_cluster_dns": True,
                }
            }
        ),
    ],
    ids=["complete", "without_route53"],
)
def test_hit_substack_rendering(tmp_path, test_config):

    substack_rendering(tmp_path, "compute-fleet-hit-substack.cfn.yaml", test_config)


def test_cw_dashboard_substack_rendering(tmp_path):
    test_config = {
        "ClusterConfigMetadata": {
            "sections": {
                "cluster": ["default"],
                "dcv": ["dcv"],
                "ebs": ["custom1", "custom2", "custom3", "custom4", "custom5"],
                "efs": ["customfs"],
                "fsx": ["fsx1"],
                "raid": ["raidgp2"],
                "scaling": ["custom"],
                "vpc": ["default"],
            }
        },
        "KeyName": "first_cluster",
        "BaseOS": "alinux2",
        "Scheduler": "slurm",
        "MasterInstanceType": "t2.micro",
        "MasterRootVolumeSize": "25",
        "ComputeRootVolumeSize": "25",
        "ProxyServer": "NONE",
        "EC2IAMRoleName": "NONE",
        "S3ReadResource": "NONE",
        "S3ReadWriteResource": "NONE",
        "EFA": "NONE",
        "EphemeralDir": "/scratch",
        "EncryptedEphemeral": "false",
        "CustomAMI": "ami-07fb283f3083e0d00",
        "PreInstallScript": "NONE",
        "PreInstallArgs": "NONE",
        "PostInstallScript": "NONE",
        "PostInstallArgs": "NONE",
        "ExtraJson": "{}",
        "AdditionalCfnTemplate": "NONE",
        "CustomChefCookbook": "NONE",
        "IntelHPCPlatform": "false",
        "ScaleDownIdleTime": "3",
        "VPCId": "vpc-034545fa84d175bc0",
        "MasterSubnetId": "subnet-021ceb759253eeb29",
        "AccessFrom": "0.0.0.0/0",
        "AdditionalSG": "NONE",
        "ComputeSubnetId": "subnet-0e49d198bb500e672",
        "ComputeSubnetCidr": "NONE",
        "UsePublicIps": "true",
        "VPCSecurityGroupId": "NONE",
        "AvailabilityZone": "eu-west-1a",
        "SharedDir": "vol1,vol2,vol3,vol4,vol5",
        "EBSSnapshotId": "NONE,NONE,NONE,NONE,NONE",
        "VolumeType": "gp2,io1,sc1,st1,io1",
        "VolumeSize": "20,20,500,500,20",
        "VolumeIOPS": "100,200,100,100,100",
        "EBSEncryption": "false,false,false,false,false",
        "EBSKMSKeyId": "NONE,NONE,NONE,NONE,NONE",
        "EBSVolumeId": "NONE,NONE,NONE,NONE,NONE",
        "NumberOfEBSVol": "5",
        "EFSOptions": "efs,NONE,generalPurpose,NONE,NONE,false,bursting,NONE,Valid",
        # "RAIDOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE", # TODO: If we use this, should ignore W2001
        "RAIDOptions": "raid,1,2,gp2,20,100,false,NONE",
        "FSXOptions": "/fsx,NONE,1200,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
        "DCVOptions": "master,8443,0.0.0.0/0",
        "CWLogOptions": "true,14",
        "EC2IAMPolicies": "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",  # FIXME could be removed, added auto
        # ,arn:aws:iam::aws:policy/CloudWatchFullAccess", # FIXME has been removed, we should see what is required
        "Architecture": "x86_64",
        "Cores": "NONE,NONE",
    }

    substack_rendering(tmp_path, "cw-dashboard-substack.cfn.yaml", test_config)  #FIXME , ["-i", "W2001"]) # to ignore W2001
    #FIXME Might have to use W2001 as if the Logs dashboard is empty, we do not use variable CWLogGroupName
    # As before, it might not be important as the test does not try to do that (and there is no point in doing that)
