import hashlib
import importlib.util
import sys
from unittest.mock import patch

import pytest
from assertpy import assert_that
from cfnlint.__main__ import main as cfnlint
from jinja2 import Environment, FileSystemLoader

spec = importlib.util.spec_from_file_location("cfn_formatter", "../utils/cfn_formatter.py")
cfn_formatter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cfn_formatter)


def substack_rendering(tmp_path, template_name, test_config):

    env = Environment(loader=FileSystemLoader(".."))
    env.filters["sha1"] = lambda value: hashlib.sha1(value.strip().encode()).hexdigest()
    env.filters["bool"] = lambda value: value.lower() == "true"
    template = env.get_template(template_name)
    output_from_parsed_template = template.render(
        config=test_config, config_version="version", tags=[{"Key": "TagKey", "Value": "TagValue"}]
    )
    rendered_file = tmp_path / template_name
    rendered_file.write_text(output_from_parsed_template)

    # Run cfn-lint
    cfn_lint_args = ["--info", str(rendered_file)]  # TODO "-i", "W2001" could be added to ignore unused vars
    with patch.object(sys, "argv", cfn_lint_args):
        assert cfnlint() == 0

    # Run format check
    assert cfn_formatter.check_formatting([str(rendered_file)], "yaml")

    return output_from_parsed_template


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
                            "enable_efa_gdr": False,
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
                                    "enable_efa_gdr": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": False,
                                    "network_interfaces": 1,
                                },
                                "multiple_spot_c5.2xlarge": {
                                    "instance_type": "c5.2xlarge",
                                    "min_count": 1,
                                    "max_count": 5,
                                    "spot_price": 1.5,
                                    "vcpus": 4,
                                    "gpus": 0,
                                    "enable_efa": False,
                                    "enable_efa_gdr": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": True,
                                    "network_interfaces": 1,
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
                                    "enable_efa_gdr": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": True,
                                    "network_interfaces": 1,
                                }
                            },
                            "compute_type": "ondemand",
                            "enable_efa": True,
                            "enable_efa_gdr": False,
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
                                    "enable_efa_gdr": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": True,
                                    "network_interfaces": 1,
                                }
                            },
                            "compute_type": "ondemand",
                            "enable_efa": False,
                            "enable_efa_gdr": False,
                            "disable_hyperthreading": True,
                            "placement_group": None,
                        },
                    },
                    "scaling": {"scaledown_idletime": 10},
                    "disable_cluster_dns": False,
                    "dashboard": {"enable": True},
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
                            "enable_efa_gdr": False,
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
                                    "enable_efa_gdr": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": True,
                                    "network_interfaces": 1,
                                },
                                "multiple_spot_c5.2xlarge": {
                                    "instance_type": "c5.2xlarge",
                                    "min_count": 1,
                                    "max_count": 5,
                                    "spot_price": 1.5,
                                    "vcpus": 4,
                                    "gpus": 0,
                                    "enable_efa": False,
                                    "enable_efa_gdr": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": True,
                                    "network_interfaces": 1,
                                },
                                # TODO: add test for multiple NICs
                            },
                        }
                    },
                    "scaling": {"scaledown_idletime": 10},
                    "disable_cluster_dns": True,
                    "dashboard": {"enable": True},
                }
            }
        ),
    ],
    ids=["complete", "without_route53"],
)
def test_hit_substack_rendering(tmp_path, test_config):

    substack_rendering(tmp_path, "compute-fleet-hit-substack.cfn.yaml", test_config)


@pytest.mark.parametrize(
    "os, scheduler, dashboard_enabled, ebs_shared_dir, ebs_volume_type, raid_options,"
    "fsx_options, efs_options, dcv_options, cw_log_options",
    [
        (
            "centos8",
            "slurm",
            True,
            "vol1,vol2,vol3,vol4,vol5",
            "gp2,io1,sc1,st1,gp2",  # No io1 metrics
            "raid,1,2,gp2,20,100,false,NONE",
            "/fsx,NONE,1200,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
            "efs,NONE,generalPurpose,NONE,NONE,false,bursting,NONE,Valid",
            "master,8443,0.0.0.0/0",
            "true,14",
        ),
        (
            "alinux",
            "sge",
            True,
            "vol1,NONE,NONE,NONE,NONE",  # single ebs section
            "io1,io1,io1,io1,io1",  # No gp2,sc1,st1 metrics
            "raid,1,2,io1,20,100,false,NONE",  # No gp2,sc1,st1 metrics
            "/fsx,NONE,1200,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
            "efs,NONE,maxIO,NONE,NONE,false,bursting,NONE,Valid",  # No conditional EFS metric (maxIO)
            "master,8443,0.0.0.0/0",
            "true,14",
        ),
        (
            "ubuntu1804",
            "torque",
            True,
            "shared",  # No ebs section
            "standard,standard,standard,standard,standard",
            "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",  # No RAID metrics
            "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",  # No FSx metrics
            "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",  # No EFS metrics
            "NONE,NONE,NONE",  # No DCV logs
            "true,14",
        ),
        (
            "alinux2",
            "awsbatch",
            True,
            "shared",
            "sc1,st1,gp2,sc1,st1",
            "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
            "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
            "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
            "NONE,NONE,NONE",
            "false,14",  # No Head Node Logs
        ),
        (
            "ubuntu1604",
            "slurm",
            False,  # No dashboard
            "vol1,vol2,vol3,vol4,vol5",
            "NONE,NONE,NONE,NONE,NONE",
            "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
            "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
            "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
            "NONE,NONE,NONE",
            "false,14",
        ),
    ],
    ids=["all_enabled", "condition_on_resources", "missing_resources_and_logs", "no_cw_logs", "no_dashboard"],
)
def test_cw_dashboard_substack_rendering(
    tmp_path,
    os,
    scheduler,
    dashboard_enabled,
    ebs_shared_dir,
    ebs_volume_type,
    raid_options,
    fsx_options,
    efs_options,
    dcv_options,
    cw_log_options,
):
    json_params = {
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
            "dashboard": {"enable": dashboard_enabled},
        }
    }
    cfn_params = {
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
        "BaseOS": os,
        "Scheduler": scheduler,
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
        "SharedDir": ebs_shared_dir,
        "EBSSnapshotId": "NONE,NONE,NONE,NONE,NONE",
        "VolumeType": ebs_volume_type,
        "VolumeSize": "20,20,500,500,20",
        "VolumeIOPS": "100,200,100,100,100",
        "EBSEncryption": "false,false,false,false,false",
        "EBSKMSKeyId": "NONE,NONE,NONE,NONE,NONE",
        "EBSVolumeId": "NONE,NONE,NONE,NONE,NONE",
        "NumberOfEBSVol": "5",
        "EFSOptions": efs_options,
        "RAIDOptions": raid_options,
        "FSXOptions": fsx_options,
        "DCVOptions": dcv_options,
        "CWLogOptions": cw_log_options,
        "EC2IAMPolicies": "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
        "Architecture": "x86_64",
        "Cores": "NONE,NONE",
    }

    rendered_template = substack_rendering(
        tmp_path, "cw-dashboard-substack.cfn.yaml", {"json_params": json_params, "cfn_params": cfn_params}
    )

    _verify_ec2_metrics_conditions(
        rendered_template, ebs_shared_dir, ebs_volume_type, raid_options, efs_options, fsx_options
    )
    _verify_head_node_logs_conditions(rendered_template, cw_log_options, os, scheduler, dcv_options)


def _verify_ec2_metrics_conditions(
    rendered_template, ebs_shared_dir, ebs_volume_type, raid_options, efs_options, fsx_options
):
    """Verify conditions related to EC2 metrics."""
    if ebs_shared_dir.split(",")[0] != "NONE":
        assert_that(rendered_template).contains("EBS Metrics")
    else:
        assert_that(rendered_template).does_not_contain("EBS Metrics")

    if raid_options.split(",")[0] != "NONE":
        assert_that(rendered_template).contains("RAID Metrics")
    else:
        assert_that(rendered_template).does_not_contain("RAID Metrics")

    # conditional EBS metrics
    if any("io1" in options for options in [ebs_volume_type, raid_options]):
        assert_that(rendered_template).contains("Consumed Read/Write Ops")
        assert_that(rendered_template).contains("Throughput Percentage")
    else:
        assert_that(rendered_template).does_not_contain("Consumed Read/Write Ops")
        assert_that(rendered_template).does_not_contain("Throughput Percentage")

    # conditional EBS and RAID metrics
    ebs_burst_balance = any(vol_type in ebs_volume_type for vol_type in ["gp1", "st1", "sc1"])
    raid_burst_balance = any(vol_type in raid_options for vol_type in ["gp1", "st1", "sc1"])
    if ebs_burst_balance or raid_burst_balance:
        assert_that(rendered_template).contains("Burst Balance")
    else:
        assert_that(rendered_template).does_not_contain("Burst Balance")

    if efs_options.split(",")[0] != "NONE":
        assert_that(rendered_template).contains("EFS Metrics")

        # conditional EFS metrics
        if "generalPurpose" in efs_options:
            assert_that(rendered_template).contains("PercentIOLimit")
        else:
            assert_that(rendered_template).does_not_contain("PercentIOLimit")
    else:
        assert_that(rendered_template).does_not_contain("EFS Metrics")

    if fsx_options.split(",")[0] != "NONE":
        assert_that(rendered_template).contains("FSx Metrics")
    else:
        assert_that(rendered_template).does_not_contain("FSx Metrics")


def _verify_head_node_logs_conditions(rendered_template, cw_log_options, os, scheduler, dcv_options):
    """Verify conditions related to the Head Node Logs section."""
    if cw_log_options.split(",")[0] != "false":
        assert_that(rendered_template).contains("Head Node Logs")

        # Conditional Scheduler logs
        if scheduler == "slurm":
            assert_that(rendered_template).contains("clustermgtd")
            assert_that(rendered_template).contains("slurm_resume")
            assert_that(rendered_template).contains("slurm_suspend")
            assert_that(rendered_template).contains("slurmctld")
            assert_that(rendered_template).does_not_contain("jobwatcher")
            assert_that(rendered_template).does_not_contain("sqswatcher")
            assert_that(rendered_template).does_not_contain("sge-qmaster")
            assert_that(rendered_template).does_not_contain("torque-server")
        elif scheduler == "sge":
            assert_that(rendered_template).contains("jobwatcher")
            assert_that(rendered_template).contains("sqswatcher")
            assert_that(rendered_template).contains("sge-qmaster")
            assert_that(rendered_template).does_not_contain("torque-server")
            assert_that(rendered_template).does_not_contain("clustermgtd")
            assert_that(rendered_template).does_not_contain("slurm_resume")
            assert_that(rendered_template).does_not_contain("slurm_suspend")
            assert_that(rendered_template).does_not_contain("slurmctld")
        elif scheduler == "torque":
            assert_that(rendered_template).contains("jobwatcher")
            assert_that(rendered_template).contains("sqswatcher")
            assert_that(rendered_template).contains("torque-server")
            assert_that(rendered_template).does_not_contain("sge-qmaster")
            assert_that(rendered_template).does_not_contain("clustermgtd")
            assert_that(rendered_template).does_not_contain("slurm_resume")
            assert_that(rendered_template).does_not_contain("slurm_suspend")
            assert_that(rendered_template).does_not_contain("slurmctld")
        else:  # scheduler == "awsbatch"
            assert_that(rendered_template).does_not_contain("jobwatcher")
            assert_that(rendered_template).does_not_contain("sqswatcher")
            assert_that(rendered_template).does_not_contain("torque-server")
            assert_that(rendered_template).does_not_contain("sge-qmaster")
            assert_that(rendered_template).does_not_contain("clustermgtd")
            assert_that(rendered_template).does_not_contain("slurm_resume")
            assert_that(rendered_template).does_not_contain("slurm_suspend")
            assert_that(rendered_template).does_not_contain("slurmctld")

        # conditional DCV logs
        if dcv_options.split(",")[0] != "NONE":
            assert_that(rendered_template).contains("NICE DCV integration logs")
            assert_that(rendered_template).contains("dcv-ext-authenticator")
            assert_that(rendered_template).contains("dcv-authenticator")
            assert_that(rendered_template).contains("dcv-agent")
            assert_that(rendered_template).contains("dcv-xsession")
            assert_that(rendered_template).contains("dcv-server")
            assert_that(rendered_template).contains("dcv-session-launcher")
            assert_that(rendered_template).contains("Xdcv")
        else:
            assert_that(rendered_template).does_not_contain("NICE DCV integration logs")

        # Conditional System logs
        if os in ["alinux", "alinux2", "centos7", "centos8"]:
            assert_that(rendered_template).contains("system-messages")
            assert_that(rendered_template).does_not_contain("syslog")
        elif os in ["ubuntu1604", "ubuntu1804"]:
            assert_that(rendered_template).contains("syslog")
            assert_that(rendered_template).does_not_contain("system-messages")

        assert_that(rendered_template).contains("cfn-init")
        assert_that(rendered_template).contains("chef-client")
        assert_that(rendered_template).contains("cloud-init")
        assert_that(rendered_template).contains("supervisord")

    else:
        assert_that(rendered_template).does_not_contain("Head Node Logs")
