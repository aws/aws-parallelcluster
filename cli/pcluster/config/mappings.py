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
from future.moves.collections import OrderedDict

from pcluster.config.param_types import (
    AdditionalIamPoliciesParam,
    BoolParam,
    ClusterSection,
    ComputeAvailabilityZoneParam,
    DisableHyperThreadingParam,
    EBSSettingsParam,
    EFSSection,
    ExtraJsonParam,
    FloatParam,
    IntParam,
    JsonParam,
    MaintainInitialSizeParam,
    MasterAvailabilityZoneParam,
    QueueSizeParam,
    Section,
    SettingsParam,
    SharedDirParam,
    SpotBidPercentageParam,
    SpotPriceParam,
)
from pcluster.config.validators import (
    base_os_validator,
    cluster_validator,
    compute_instance_type_validator,
    dcv_enabled_validator,
    disable_hyperthreading_validator,
    ebs_settings_validator,
    ec2_ami_validator,
    ec2_ebs_snapshot_validator,
    ec2_iam_policies_validator,
    ec2_iam_role_validator,
    ec2_instance_type_validator,
    ec2_key_pair_validator,
    ec2_placement_group_validator,
    ec2_security_group_validator,
    ec2_subnet_id_validator,
    ec2_volume_validator,
    ec2_vpc_id_validator,
    efa_validator,
    efs_id_validator,
    efs_validator,
    fsx_id_validator,
    fsx_imported_file_chunk_size_validator,
    fsx_os_support,
    fsx_storage_capacity_validator,
    fsx_validator,
    intel_hpc_validator,
    kms_key_validator,
    raid_volume_iops_validator,
    s3_bucket_validator,
    scheduler_validator,
    shared_dir_validator,
    url_validator,
)
from pcluster.constants import CIDR_ALL_IPS

# This file contains a definition of all the sections and the parameters configurable by the user
# in the configuration file.

# For each section you can define:
#
# - type, the class to use to represent this section (default: Section)
# - key, the key used in configuration file that identifies the section type
#   (e.g [cluster default] -> "cluster" is the key)
# - default_label, the label to use for the section when initializing from CFN or from default values.
#   (e.g [cluster default] -> "default" is the key)
# - validator, a function to use to validate the section.
#   It is called for all the parameters once all of them are initialized.
# - cfn_param_mapping, the CFN parameters to use for the to/from_cfn conversion.
#   it is used for sections that are converted to a single CFN parameter, e.g. RAID, EFS, FSX
# - params, a dictionary containing all the parameters available for that section

# For each parameter you can define:
#
# - type the class to use to represent this section (default: Param, a string parameter)
# - cfn_param_mapping the CFN parameters to use for the to/from_cfn conversion.
# - allowed_values, a list of allowed values or a regex. It is evaluated at parsing time.
# - validators, a list of functions to use to validate the param.
#   It is called for all the parameters once all of them are initialized.
# - default, a default value for the internal representation, if not specified the value will be None
# - referred_section, it is a special attribute used only for *SettingsParam,
#   the parameters that refers to other sections in the file (e.g. vpc_settings)

# fmt: off

# Utility dictionary containing all the common regex used in the section mapping.
ALLOWED_VALUES = {
    "ami_id": r"^ami-[0-9a-z]{8}$|^ami-[0-9a-z]{17}$",
    "cidr": r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/(0|1[6-9]|2[0-9]|3[0-2])$",
    "efs_fs_id": r"^fs-[0-9a-z]{8}$|^fs-[0-9a-z]{17}|NONE$",
    "file_path": r"\/?[\w:]+",
    "fsx_fs_id": r"^fs-[0-9a-z]{17}|NONE$",
    "greater_than_25": r"^([0-9]+[0-9]{2}|[3-9][0-9]|2[5-9])$",
    "security_group_id": r"^sg-[0-9a-z]{8}$|^sg-[0-9a-z]{17}$",
    "snapshot_id": r"^snap-[0-9a-z]{8}$|^snap-[0-9a-z]{17}$",
    "subnet_id": r"^subnet-[0-9a-z]{8}$|^subnet-[0-9a-z]{17}$",
    "volume_id": r"^vol-[0-9a-z]{8}$|^vol-[0-9a-z]{17}$",
    "volume_types": ["standard", "io1", "gp2", "st1", "sc1"],
    "vpc_id": r"^vpc-[0-9a-z]{8}$|^vpc-[0-9a-z]{17}$",
    "deployment_type": ["SCRATCH_1", "SCRATCH_2", "PERSISTENT_1"],
    "per_unit_storage_throughput": [50, 100, 200],
}

AWS = {
    "type": Section,
    "key": "aws",
    "params": {
        "aws_access_key_id": {},
        "aws_secret_access_key": {},
        "aws_region_name": {
            "default": "us-east-1",  # TODO add regex
        },
    }
}

GLOBAL = {
    "type": Section,
    "key": "global",
    "params": {
        "cluster_template": {
            # TODO This could be a SettingsParam referring to a CLUSTER section
            "default": "default",
        },
        "update_check": {
            "type": BoolParam,
            "default": True,
        },
        "sanity_check": {
            "type": BoolParam,
            "default": True,
        },
    }
}

ALIASES = {
    "type": Section,
    "key": "aliases",
    "params": {
        "ssh": {
            "default": "ssh {CFN_USER}@{MASTER_IP} {ARGS}"
        },
    }
}

SCALING = {
    "type": Section,
    "key": "scaling",
    "default_label": "default",
    "params": {
        "scaledown_idletime": {
            "type": IntParam,
            "default": 10,
            "cfn_param_mapping": "ScaleDownIdleTime",
        }
    }
}

VPC = {
    "type": Section,
    "key": "vpc",
    "default_label": "default",
    "params": {
        "vpc_id": {
            "cfn_param_mapping": "VPCId",
            "allowed_values": ALLOWED_VALUES["vpc_id"],
            "validators": [ec2_vpc_id_validator],
        },
        "master_subnet_id": {
            "cfn_param_mapping": "MasterSubnetId",
            "allowed_values": ALLOWED_VALUES["subnet_id"],
            "validators": [ec2_subnet_id_validator],
        },
        "ssh_from": {
            "default": CIDR_ALL_IPS,
            "allowed_values": ALLOWED_VALUES["cidr"],
            "cfn_param_mapping": "AccessFrom",
        },
        "additional_sg": {
            "cfn_param_mapping": "AdditionalSG",
            "allowed_values": ALLOWED_VALUES["security_group_id"],
            "validators": [ec2_security_group_validator],
        },
        "compute_subnet_id": {
            "cfn_param_mapping": "ComputeSubnetId",
            "allowed_values": ALLOWED_VALUES["subnet_id"],
            "validators": [ec2_subnet_id_validator],
        },
        "compute_subnet_cidr": {
            "cfn_param_mapping": "ComputeSubnetCidr",
            "allowed_values": ALLOWED_VALUES["cidr"],
        },
        "use_public_ips": {
            "type": BoolParam,
            "default": True,
            "cfn_param_mapping": "UsePublicIps",
        },
        "vpc_security_group_id": {
            "cfn_param_mapping": "VPCSecurityGroupId",
            "allowed_values": ALLOWED_VALUES["security_group_id"],
            "validators": [ec2_security_group_validator],
        },
        "master_availability_zone": {
            # NOTE: this is not exposed as a configuration parameter
            "type": MasterAvailabilityZoneParam,
            "cfn_param_mapping": "AvailabilityZone",
        },
        "compute_availability_zone": {
            # NOTE: this is not exposed as a configuration parameter
            "type": ComputeAvailabilityZoneParam,
        }
    },
}

EBS = {
    "type": Section,
    "key": "ebs",
    "default_label": "default",
    "params": {
        "shared_dir": {
            "allowed_values": ALLOWED_VALUES["file_path"],
            "cfn_param_mapping": "SharedDir",
            "validators": [shared_dir_validator],
        },
        "ebs_snapshot_id": {
            "allowed_values": ALLOWED_VALUES["snapshot_id"],
            "cfn_param_mapping": "EBSSnapshotId",
            "validators": [ec2_ebs_snapshot_validator],
        },
        "volume_type": {
            "default": "gp2",
            "allowed_values": ALLOWED_VALUES["volume_types"],
            "cfn_param_mapping": "VolumeType",
        },
        "volume_size": {
            "type": IntParam,
            "default": 20,
            "cfn_param_mapping": "VolumeSize",
        },
        "volume_iops": {
            "type": IntParam,
            "default": 100,
            "cfn_param_mapping": "VolumeIOPS",
        },
        "encrypted": {
            "type": BoolParam,
            "cfn_param_mapping": "EBSEncryption",
            "default": False,
        },
        "ebs_kms_key_id": {
            "cfn_param_mapping": "EBSKMSKeyId",
            "validators": [kms_key_validator],
        },
        "ebs_volume_id": {
            "cfn_param_mapping": "EBSVolumeId",
            "allowed_values": ALLOWED_VALUES["volume_id"],
            "validators": [ec2_volume_validator],
        },
    },
}

EFS = {
    "key": "efs",
    "type": EFSSection,
    "default_label": "default",
    "validators": [efs_validator],
    "cfn_param_mapping": "EFSOptions",  # All the parameters in the section are converted into a single CFN parameter
    "params": OrderedDict(  # Use OrderedDict because the parameters must respect the order in the CFN parameter
        [
            ("shared_dir", {
                "allowed_values": ALLOWED_VALUES["file_path"],
                "validators": [shared_dir_validator],
            }),
            ("efs_fs_id", {
                "allowed_values": ALLOWED_VALUES["efs_fs_id"],
                "validators": [efs_id_validator],
            }),
            ("performance_mode", {
                "default": "generalPurpose",
                "allowed_values": ["generalPurpose", "maxIO"],
            }),
            ("efs_kms_key_id", {
                "validators": [kms_key_validator],
            }),
            ("provisioned_throughput", {
                "allowed_values": r"^([0-9]{1,3}|10[0-1][0-9]|102[0-4])(\.[0-9])?$",  # 0.0 to 1024.0
                "type": FloatParam,
            }),
            ("encrypted", {
                "type": BoolParam,
                "default": False,
            }),
            ("throughput_mode", {
                "default": "bursting",
                "allowed_values": ["provisioned", "bursting"],
            }),
        ]
    )
}

RAID = {
    "type": Section,
    "key": "raid",
    "default_label": "default",
    "cfn_param_mapping": "RAIDOptions",  # All the parameters in the section are converted into a single CFN parameter
    "params": OrderedDict(  # Use OrderedDict because the parameters must respect the order in the CFN parameter
        [
            ("shared_dir", {
                "allowed_values": ALLOWED_VALUES["file_path"],
                "validators": [shared_dir_validator],
            }),
            ("raid_type", {
                "type": IntParam,
                "allowed_values": [0, 1],
            }),
            ("num_of_raid_volumes", {
                "type": IntParam,
                "allowed_values": "^[1-5]$",
            }),
            ("volume_type", {
                "default": "gp2",
                "allowed_values": ALLOWED_VALUES["volume_types"],
            }),
            ("volume_size", {
                "type": IntParam,
                "default": 20,
            }),
            ("volume_iops", {
                "type": IntParam,
                "default": 100,
                "validators": [raid_volume_iops_validator],
            }),
            ("encrypted", {
                "type": BoolParam,
                "default": False,
            }),
            ("ebs_kms_key_id", {
                "validators": [kms_key_validator],
            }),
        ]
    )
}


FSX = {
    "type": Section,
    "key": "fsx",
    "default_label": "default",
    "validators": [fsx_validator, fsx_storage_capacity_validator],
    "cfn_param_mapping": "FSXOptions",  # All the parameters in the section are converted into a single CFN parameter
    "params": OrderedDict(  # Use OrderedDict because the parameters must respect the order in the CFN parameter
        [
            ("shared_dir", {
                "allowed_values": ALLOWED_VALUES["file_path"],
                "validators": [shared_dir_validator],
            }),
            ("fsx_fs_id", {
                "allowed_values": ALLOWED_VALUES["fsx_fs_id"],
                "validators": [fsx_id_validator],
            }),
            ("storage_capacity", {
                "type": IntParam,
            }),
            ("fsx_kms_key_id", {
                "validators": [kms_key_validator],
            }),
            ("imported_file_chunk_size", {
                "type": IntParam,
                "validators": [fsx_imported_file_chunk_size_validator]
            }),
            ("export_path", {
                "validators": [s3_bucket_validator],
            }),
            ("import_path", {
                "validators": [s3_bucket_validator],
            }),
            ("weekly_maintenance_start_time", {
                "allowed_values": r"NONE|^[1-7]:([01]\d|2[0-3]):?([0-5]\d)$",
            }),
            ("deployment_type", {
                "allowed_values": ALLOWED_VALUES["deployment_type"],
            }),
            ("per_unit_storage_throughput", {
                "type": IntParam,
                "allowed_values": ALLOWED_VALUES["per_unit_storage_throughput"],
            }),
        ]
    )
}

DCV = {
    "type": Section,
    "key": "dcv",
    "default_label": "default",
    "cfn_param_mapping": "DCVOptions",  # All the parameters in the section are converted into a single CFN parameter
    "params": OrderedDict(  # Use OrderedDict because the parameters must respect the order in the CFN parameter
        [
            ("enable", {
                "allowed_values": ["master"],
                "validators": [dcv_enabled_validator],
            }),
            ("port", {
                "type": IntParam,
                "default": 8443,
            }),
            ("access_from", {
                "default": CIDR_ALL_IPS,
                "allowed_values": ALLOWED_VALUES["cidr"],
            }),
        ]
    )
}

CW_LOG = {
    "type": Section,
    "key": "cw_log",
    "default_label": "default",
    "cfn_param_mapping": "CWLogOptions",  # Stringify params into single CFN parameter
    "params": OrderedDict([
        ("enable", {
            "type": BoolParam,
            "default": True,
        }),
        ("retention_days", {
            "type": IntParam,
            "default": 14,
            "cfn_param_mapping": "CWLogEventRententionDays",
            "allowed_values": [
                1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653
            ]
        }),
    ])
}

CLUSTER = {
    "type": ClusterSection,
    "key": "cluster",
    "default_label": "default",
    "validators": [cluster_validator],
    "params": OrderedDict(
        [  # OrderedDict due to conditional defaults values
            ("key_name", {
                "cfn_param_mapping": "KeyName",
                "validators": [ec2_key_pair_validator],
            }),
            ("base_os", {
                "cfn_param_mapping": "BaseOS",
                "allowed_values": ["alinux", "alinux2", "ubuntu1604", "ubuntu1804", "centos6", "centos7"],
                "validators": [base_os_validator],
                "required": True,
            }),
            ("scheduler", {
                "cfn_param_mapping": "Scheduler",
                "allowed_values": ["awsbatch", "sge", "slurm", "torque"],
                "validators": [scheduler_validator],
                "required": True,
            }),
            ("placement_group", {
                "cfn_param_mapping": "PlacementGroup",
                "validators": [ec2_placement_group_validator],
            }),
            ("placement", {
                "default": "compute",
                "cfn_param_mapping": "Placement",
                "allowed_values": ["cluster", "compute"],
            }),
            # Master
            ("master_instance_type", {
                "default": "t2.micro",
                "cfn_param_mapping": "MasterInstanceType",
                "validators": [ec2_instance_type_validator],
            }),
            ("master_root_volume_size", {
                "type": IntParam,
                "default": 25,
                "allowed_values": ALLOWED_VALUES["greater_than_25"],
                "cfn_param_mapping": "MasterRootVolumeSize",
            }),
            # Compute fleet
            ("compute_instance_type", {
                "default":
                    lambda section:
                        "optimal" if section and section.get_param_value("scheduler") == "awsbatch" else "t2.micro",
                "cfn_param_mapping": "ComputeInstanceType",
                "validators": [compute_instance_type_validator],
            }),
            ("compute_root_volume_size", {
                "type": IntParam,
                "default": 25,
                "allowed_values": ALLOWED_VALUES["greater_than_25"],
                "cfn_param_mapping": "ComputeRootVolumeSize",
            }),
            ("initial_queue_size", {
                "type": QueueSizeParam,
                "default": 0,
                "cfn_param_mapping": "DesiredSize",  # TODO verify the update case
            }),
            ("max_queue_size", {
                "type": QueueSizeParam,
                "default": 10,
                "cfn_param_mapping": "MaxSize",
            }),
            ("maintain_initial_size", {
                "type": MaintainInitialSizeParam,
                "default": False,
                "cfn_param_mapping": "MinSize",
            }),
            ("min_vcpus", {
                "type": QueueSizeParam,
                "default": 0,
                "cfn_param_mapping": "MinSize",
            }),
            ("desired_vcpus", {
                "type": QueueSizeParam,
                "default": 4,
                "cfn_param_mapping": "DesiredSize",
            }),
            ("max_vcpus", {
                "type": QueueSizeParam,
                "default": 10,
                "cfn_param_mapping": "MaxSize",
            }),
            ("cluster_type", {
                "default": "ondemand",
                "allowed_values": ["ondemand", "spot"],
                "cfn_param_mapping": "ClusterType",
            }),
            ("spot_price", {
                "type": SpotPriceParam,
                "default": 0,
                "cfn_param_mapping": "SpotPrice",
            }),
            ("spot_bid_percentage", {
                "type": SpotBidPercentageParam,
                "default": 0,
                "cfn_param_mapping": "SpotPrice",
                "allowed_values": r"^(100|[1-9][0-9]|[0-9])$",  # 0 <= value <= 100
            }),
            # Access and networking
            ("proxy_server", {
                "cfn_param_mapping": "ProxyServer",
            }),
            ("ec2_iam_role", {
                "cfn_param_mapping": "EC2IAMRoleName",
                "validators": [ec2_iam_role_validator],  # TODO add regex
            }),
            ("s3_read_resource", {
                "cfn_param_mapping": "S3ReadResource",
            }),
            ("s3_read_write_resource", {
                "cfn_param_mapping": "S3ReadWriteResource",
            }),
            (
                "disable_hyperthreading",
                {
                    "type": DisableHyperThreadingParam,
                    "default": False,
                    "cfn_param_mapping": "Cores",
                    "validators": [disable_hyperthreading_validator],
                },
            ),
            # Customization
            ("template_url", {
                # TODO add regex
                "validators": [url_validator],
            }),
            ("shared_dir", {
                "type": SharedDirParam,
                "allowed_values": ALLOWED_VALUES["file_path"],
                "cfn_param_mapping": "SharedDir",
                "default": "/shared",
                "validators": [shared_dir_validator],
            }),
            ("enable_efa", {
                "allowed_values": ["compute"],
                "cfn_param_mapping": "EFA",
                "validators": [efa_validator],
            }),
            ("ephemeral_dir", {
                "allowed_values": ALLOWED_VALUES["file_path"],
                "default": "/scratch",
                "cfn_param_mapping": "EphemeralDir",
            }),
            ("encrypted_ephemeral", {
                "default": False,
                "type": BoolParam,
                "cfn_param_mapping": "EncryptedEphemeral",
            }),
            ("custom_ami", {
                "cfn_param_mapping": "CustomAMI",
                "allowed_values": ALLOWED_VALUES["ami_id"],
                "validators": [ec2_ami_validator],
            }),
            ("pre_install", {
                "cfn_param_mapping": "PreInstallScript",
                # TODO add regex
                "validators": [url_validator],
            }),
            ("pre_install_args", {
                "cfn_param_mapping": "PreInstallArgs",
            }),
            ("post_install", {
                "cfn_param_mapping": "PostInstallScript",
                # TODO add regex
                "validators": [url_validator],
            }),
            ("post_install_args", {
                "cfn_param_mapping": "PostInstallArgs",
            }),
            ("extra_json", {
                "type": ExtraJsonParam,
                "cfn_param_mapping": "ExtraJson",
            }),
            ("additional_cfn_template", {
                "cfn_param_mapping": "AdditionalCfnTemplate",
                # TODO add regex
                "validators": [url_validator],
            }),
            ("tags", {
                "type": JsonParam,
            }),
            ("custom_chef_cookbook", {
                "cfn_param_mapping": "CustomChefCookbook",
                # TODO add regex
                "validators": [url_validator],
            }),
            ("custom_awsbatch_template_url", {
                "cfn_param_mapping": "CustomAWSBatchTemplateURL",
                # TODO add regex
                "validators": [url_validator],
            }),
            ("enable_intel_hpc_platform", {
                "default": False,
                "type": BoolParam,
                "cfn_param_mapping": "IntelHPCPlatform",
                "validators": [intel_hpc_validator],
            }),
            # Settings
            ("scaling_settings", {
                "type": SettingsParam,
                "default": "default",  # set a value to create always the internal structure for the scaling section
                "referred_section": SCALING,
            }),
            ("vpc_settings", {
                "type": SettingsParam,
                "default": "default",  # set a value to create always the internal structure for the vpc section
                "referred_section": VPC,
            }),
            ("ebs_settings", {
                "type": EBSSettingsParam,
                "referred_section": EBS,
                "validators": [ebs_settings_validator],
            }),
            ("efs_settings", {
                "type": SettingsParam,
                "referred_section": EFS,
            }),
            ("raid_settings", {
                "type": SettingsParam,
                "referred_section": RAID,
            }),
            ("fsx_settings", {
                "type": SettingsParam,
                "referred_section": FSX,
                "validators": [fsx_os_support],
            }),
            ("dcv_settings", {
                "type": SettingsParam,
                "referred_section": DCV,
            }),
            ("cw_log_settings", {
                "type": SettingsParam,
                "referred_section": CW_LOG,
            }),
            # Moved from the "Access and Networking" section because its configuration is
            # dependent on multiple other parameters from within this section.
            ("additional_iam_policies", {
                "type": AdditionalIamPoliciesParam,
                "cfn_param_mapping": "EC2IAMPolicies",
                "validators": [ec2_iam_policies_validator],
            }),
        ]
    )
}

# fmt: on
