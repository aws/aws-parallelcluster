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

import boto3

from pcluster.config.cfn_param_types import (
    AdditionalIamPoliciesCfnParam,
    ArgsCfnParam,
    BaseOSCfnParam,
    BoolCfnParam,
    CfnSection,
    ClusterCfnSection,
    ClusterConfigMetadataCfnParam,
    ComputeAvailabilityZoneCfnParam,
    ComputeInstanceTypeCfnParam,
    DisableHyperThreadingCfnParam,
    EBSSettingsCfnParam,
    EFSCfnSection,
    ExtraJsonCfnParam,
    FloatCfnParam,
    HeadNodeAvailabilityZoneCfnParam,
    HeadNodeInstanceTypeCfnParam,
    IntCfnParam,
    MaintainInitialSizeCfnParam,
    NetworkInterfacesCountCfnParam,
    QueueSizeCfnParam,
    SettingsCfnParam,
    SharedDirCfnParam,
    SpotBidPercentageCfnParam,
    SpotPriceCfnParam,
    TagsParam,
    VolumeIopsParam,
    VolumeSizeParam,
)
from pcluster.config.json_param_types import (
    BooleanJsonParam,
    DefaultComputeQueueJsonParam,
    FloatJsonParam,
    IntJsonParam,
    JsonParam,
    JsonSection,
    QueueJsonSection,
    ScaleDownIdleTimeJsonParam,
    SettingsJsonParam,
)
from pcluster.config.param_types import Visibility
from pcluster.config.update_policy import UpdatePolicy
from pcluster.constants import CIDR_ALL_IPS, FSX_HDD_THROUGHPUT, FSX_SSD_THROUGHPUT, SUPPORTED_ARCHITECTURES

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
    "cidr": r"^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}"
            r"([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])"
            r"(\/([0-9]|[1-2][0-9]|3[0-2]))$",
    "efs_fs_id": r"^fs-[0-9a-z]{8}$|^fs-[0-9a-z]{17}|NONE$",
    "file_path": r"^\/?[^\/.\\][^\/\\]*(\/[^\/.\\][^\/]*)*$",
    "fsx_fs_id": r"^fs-[0-9a-z]{17}|NONE$",
    "greater_than_25": r"^([0-9]+[0-9]{2}|[3-9][0-9]|2[5-9])$",
    "security_group_id": r"^sg-[0-9a-z]{8}$|^sg-[0-9a-z]{17}$",
    "snapshot_id": r"^snap-[0-9a-z]{8}$|^snap-[0-9a-z]{17}$",
    "subnet_id": r"^subnet-[0-9a-z]{8}$|^subnet-[0-9a-z]{17}$",
    "volume_id": r"^vol-[0-9a-z]{8}$|^vol-[0-9a-z]{17}$",
    "volume_types": ["standard", "io1", "io2", "gp2", "st1", "sc1", "gp3"],
    "vpc_id": r"^vpc-[0-9a-z]{8}$|^vpc-[0-9a-z]{17}$",
    "fsx_deployment_type": ["SCRATCH_1", "SCRATCH_2", "PERSISTENT_1"],
    "fsx_ssd_throughput": FSX_SSD_THROUGHPUT,
    "fsx_hdd_throughput": FSX_HDD_THROUGHPUT,
    "architectures": SUPPORTED_ARCHITECTURES,
    "fsx_auto_import_policy": ["NEW", "NEW_CHANGED"],
    "fsx_storage_type": ["SSD", "HDD"],
    "fsx_drive_cache_type": ["READ"]
}

AWS = {
    "type": CfnSection,
    "key": "aws",
    "params": {
        "aws_access_key_id": {
            "update_policy": UpdatePolicy.IGNORED
        },
        "aws_secret_access_key": {
            "update_policy": UpdatePolicy.IGNORED
        },
        "aws_region_name": {
            "default": boto3.session.Session().region_name,
            "update_policy": UpdatePolicy.IGNORED
        },
    }
}

GLOBAL = {
    "type": CfnSection,
    "key": "global",
    "params": OrderedDict(
        [
            ("cluster_template", {
                # TODO This could be a SettingsParam referring to a CLUSTER section
                "default": "default",
                "update_policy": UpdatePolicy.IGNORED
            }),
            ("update_check", {
                "type": BoolCfnParam,
                "default": True,
                "update_policy": UpdatePolicy.IGNORED
            }),
            ("sanity_check", {
                "type": BoolCfnParam,
                "default": True,
                "update_policy": UpdatePolicy.IGNORED
            }),
        ]
    )
}

ALIASES = {
    "type": CfnSection,
    "key": "aliases",
    "params": {
        "ssh": {
            "default": "ssh {CFN_USER}@{MASTER_IP} {ARGS}",
            "update_policy": UpdatePolicy.IGNORED
        },
    }
}

SCALING = {
    "type": CfnSection,
    "key": "scaling",
    "default_label": "default",
    "autocreate": True,
    "params": {
        "scaledown_idletime": {
            "type": IntCfnParam,
            "default": 10,
            "cfn_param_mapping": "ScaleDownIdleTime",
        },
        "_scaledown_idletime": {
            "type": ScaleDownIdleTimeJsonParam,
            "default": 10,
            # This param is managed automatically (it's a copy of scaledown_idletime for Json param types)
            "visibility": Visibility.PRIVATE,
        },
    }
}

VPC = {
    "type": CfnSection,
    "key": "vpc",
    "default_label": "default",
    "autocreate": True,
    "params": OrderedDict([
        ("vpc_id", {
            "cfn_param_mapping": "VPCId",
            "required": True,
            "allowed_values": ALLOWED_VALUES["vpc_id"],  # does not apply to pcluster 3.0
        }),
        ("master_subnet_id", {
            "cfn_param_mapping": "MasterSubnetId",
            "required": True,
        }),
        ("ssh_from", {
            "default": CIDR_ALL_IPS,
            "cfn_param_mapping": "AccessFrom",
        }),
        ("additional_sg", {
            "cfn_param_mapping": "AdditionalSG",
        }),
        ("compute_subnet_id", {
            "cfn_param_mapping": "ComputeSubnetId",
        }),
        ("compute_subnet_cidr", {
            "cfn_param_mapping": "ComputeSubnetCidr",
            "allowed_values": ALLOWED_VALUES["cidr"],
        }),
        ("use_public_ips", {
            "type": BoolCfnParam,
            "default": True,
            "cfn_param_mapping": "UsePublicIps",
        }),
        ("vpc_security_group_id", {
            "cfn_param_mapping": "VPCSecurityGroupId",
        }),
        ("master_availability_zone", {
            # NOTE: this is not exposed as a configuration parameter
            "type": HeadNodeAvailabilityZoneCfnParam,
            "cfn_param_mapping": "AvailabilityZone",
            "visibility": Visibility.PRIVATE
        }),
        ("compute_availability_zone", {
            # NOTE: this is not exposed as a configuration parameter
            "type": ComputeAvailabilityZoneCfnParam,
            "visibility": Visibility.PRIVATE
        })
    ]),
}

EBS = {
    "type": CfnSection,
    "key": "ebs",
    "default_label": "default",
    "max_resources": 5,
    "params": OrderedDict([  # Use OrderedDict because the in python 3.5 a dict is not ordered by default, need it in
        # the test of hit converter
        ("shared_dir", {
            "cfn_param_mapping": "SharedDir",
        }),
        ("ebs_snapshot_id", {
            "cfn_param_mapping": "EBSSnapshotId",
        }),
        ("volume_type", {
            "default": "gp2",
            "cfn_param_mapping": "VolumeType",
        }),
        ("volume_size", {
            "type": VolumeSizeParam,
            "cfn_param_mapping": "VolumeSize",
        }),
        ("volume_iops", {
            "type": VolumeIopsParam,
            "cfn_param_mapping": "VolumeIOPS",
        }),
        ("encrypted", {
            "type": BoolCfnParam,
            "cfn_param_mapping": "EBSEncryption",
            "default": False,
        }),
        ("ebs_kms_key_id", {
            "cfn_param_mapping": "EBSKMSKeyId",
        }),
        ("ebs_volume_id", {
            "cfn_param_mapping": "EBSVolumeId",
        }),
        ("volume_throughput", {
            "type": IntCfnParam,
            "cfn_param_mapping": "VolumeThroughput",
            "default": 125
        })
    ]),
}

EFS = {
    "key": "efs",
    "type": EFSCfnSection,
    "default_label": "default",
    "cfn_param_mapping": "EFSOptions",  # All the parameters in the section are converted into a single CFN parameter
    "params": OrderedDict(  # Use OrderedDict because the parameters must respect the order in the CFN parameter
        [
            ("shared_dir", {
            }),
            ("efs_fs_id", {
            }),
            ("performance_mode", {
                "default": "generalPurpose",
            }),
            ("efs_kms_key_id", {
            }),
            ("provisioned_throughput", {
                "type": FloatCfnParam,
            }),
            ("encrypted", {
                "type": BoolCfnParam,
                "default": False,
            }),
            ("throughput_mode", {
                "default": "bursting",
            }),
        ]
    )
}

RAID = {
    "type": CfnSection,
    "key": "raid",
    "default_label": "default",
    "cfn_param_mapping": "RAIDOptions",  # All the parameters in the section are converted into a single CFN parameter
    "params": OrderedDict(  # Use OrderedDict because the parameters must respect the order in the CFN parameter
        [
            ("shared_dir", {
            }),
            ("raid_type", {
                "type": IntCfnParam,
            }),
            ("num_of_raid_volumes", {
                "type": IntCfnParam,
                "default": 2,

            }),
            ("volume_type", {
                "default": "gp2",
            }),
            ("volume_size", {
                "type": IntCfnParam,
                "default": 20,
            }),
            ("volume_iops", {
                "type": VolumeIopsParam,
            }),
            ("encrypted", {
                "type": BoolCfnParam,
                "default": False,
            }),
            ("ebs_kms_key_id", {
            }),
            ("volume_throughput", {
                "type": IntCfnParam,
                "default": 125,
                "cfn_param_mapping": "VolumeThroughput",
            }),
        ]
    )
}


FSX = {
    "type": CfnSection,
    "key": "fsx",
    "default_label": "default",
    "cfn_param_mapping": "FSXOptions",  # All the parameters in the section are converted into a single CFN parameter
    "params": OrderedDict(  # Use OrderedDict because the parameters must respect the order in the CFN parameter
        [
            ("shared_dir", {
            }),
            ("fsx_fs_id", {
            }),
            ("storage_capacity", {
                "type": IntCfnParam,
            }),
            ("fsx_kms_key_id", {
            }),
            ("imported_file_chunk_size", {
                "type": IntCfnParam,
            }),
            ("export_path", {
            }),
            ("import_path", {
            }),
            ("weekly_maintenance_start_time", {
                "allowed_values": r"NONE|^[1-7]:([01]\d|2[0-3]):([0-5]\d)$",  # To be migrated
            }),
            ("deployment_type", {
            }),
            ("per_unit_storage_throughput", {
                "type": IntCfnParam,
            }),
            ("daily_automatic_backup_start_time", {
            }),
            ("automatic_backup_retention_days", {
                "type": IntCfnParam,
            }),
            ("copy_tags_to_backups", {
                "type": BoolCfnParam,
            }),
            ("fsx_backup_id", {
            }),
            ("auto_import_policy", {
            }),
            ("storage_type", {
            }),
            ("drive_cache_type", {
                "default": "NONE",
            })
        ]
    )
}

DCV = {
    "type": CfnSection,
    "key": "dcv",
    "default_label": "default",
    "cfn_param_mapping": "DCVOptions",  # All the parameters in the section are converted into a single CFN parameter
    "params": OrderedDict(  # Use OrderedDict because the parameters must respect the order in the CFN parameter
        [
            ("enable", {
                "allowed_values": ["master"],  # does not apply to pcluster 3.0
            }),
            ("port", {
                "type": IntCfnParam,
                "default": 8443,
            }),
            ("access_from", {
                "default": CIDR_ALL_IPS,
            }),
        ]
    )
}

CW_LOG = {
    "type": CfnSection,
    "key": "cw_log",
    "default_label": "default",
    "cfn_param_mapping": "CWLogOptions",  # Stringify params into single CFN parameter
    "params": OrderedDict([
        ("enable", {
            "type": BoolCfnParam,
            "default": True,
        }),
        ("retention_days", {
            "type": IntCfnParam,
            "default": 14,
            "cfn_param_mapping": "CWLogEventRententionDays",
        }),
    ])
}

DASHBOARD = {
    "type": JsonSection,
    "key": "dashboard",
    "default_label": "default",
    "params": OrderedDict([
        ("enable", {
            "type": BooleanJsonParam,
            "default": True,
        }),
    ])
}

COMPUTE_RESOURCE = {
    "type": JsonSection,
    "key": "compute_resource",
    "default_label": "default",
    "max_resources": 3,
    "params": OrderedDict([
        ("instance_type", {
            "type": JsonParam,
            "required": True,
        }),
        ("min_count", {
            "type": IntJsonParam,
            "default": 0,
        }),
        ("max_count", {
            "type": IntJsonParam,
            "default": 10,
        }),
        ("initial_count", {
            "type": IntJsonParam,
            # initial_count only takes effect on cluster creation
        }),
        ("spot_price", {
            "type": FloatJsonParam,
            "default": 0,
        }),
        ("vcpus", {
            "type": IntJsonParam,
            # This param is managed automatically
            "visibility": Visibility.PRIVATE,
            "default": 0
        }),
        ("gpus", {
            "type": IntJsonParam,
            # This param is managed automatically
            "visibility": Visibility.PRIVATE,
            "default": 0
        }),
        ("network_interfaces", {
            "type": IntJsonParam,
            # This param is managed automatically
            "visibility": Visibility.PRIVATE,
            "default": 0
        }),
        ("enable_efa", {
            "type": BooleanJsonParam,
            # This param is managed automatically
            "visibility": Visibility.PRIVATE,
            "default": False
        }),
        ("enable_efa_gdr", {
            "type": BooleanJsonParam,
            # This param is managed automatically
            "visibility": Visibility.PRIVATE,
            "default": False
        }),
        ("disable_hyperthreading", {
            "type": BooleanJsonParam,
            # This param is managed automatically
            "visibility": Visibility.PRIVATE,
            "default": False
        }),
        ("disable_hyperthreading_via_cpu_options", {
            "type": BooleanJsonParam,
            # This param is managed automatically
            "visibility": Visibility.PRIVATE,
            "default": False
        }),
    ])
}

QUEUE = {
    "type": QueueJsonSection,
    "key": "queue",
    "default_label": "default",
    "max_resources": 5,
    "params": OrderedDict([
        ("compute_type", {
            "type": JsonParam,
            "default": "ondemand",
        }),
        ("enable_efa", {
            "type": BooleanJsonParam,
        }),
        ("enable_efa_gdr", {
            "type": BooleanJsonParam,
        }),
        ("disable_hyperthreading", {
            "type": BooleanJsonParam,
        }),
        ("placement_group", {
            "type": JsonParam,
        }),
        ("compute_resource_settings", {
            "type": SettingsJsonParam,
            "referred_section": COMPUTE_RESOURCE,
            "required": True,
        }),
    ])
}

CLUSTER_COMMON_PARAMS = [
    # OrderedDict due to conditional defaults values
    ("cluster_config_metadata", {
        # NOTE: this is not exposed as a configuration parameter
        "type": ClusterConfigMetadataCfnParam,
        "cfn_param_mapping": "ClusterConfigMetadata",
        "visibility": Visibility.PRIVATE,
    }),
    ("key_name", {
        "cfn_param_mapping": "KeyName",
        "required": True,
    }),
    ("scheduler", {
        "cfn_param_mapping": "Scheduler",
        "required": True,
    }),
    # Head node
    ("master_instance_type", {
        "type": HeadNodeInstanceTypeCfnParam,
        "cfn_param_mapping": "MasterInstanceType",
    }),
    ("master_root_volume_size", {
        "type": IntCfnParam,
        "default": 25,
        "cfn_param_mapping": "MasterRootVolumeSize",
    }),
    ("base_os", {
        "type": BaseOSCfnParam,
        "cfn_param_mapping": "BaseOS",
        "required": True,
    }),
    # Compute fleet
    ("compute_root_volume_size", {
        "type": IntCfnParam,
        "default": 25,
        "cfn_param_mapping": "ComputeRootVolumeSize",
    }),
    # Access and networking
    ("proxy_server", {
        "cfn_param_mapping": "ProxyServer",
    }),
    ("ec2_iam_role", {
        "cfn_param_mapping": "EC2IAMRoleName",
    }),
    ("s3_read_resource", {
        "cfn_param_mapping": "S3ReadResource",
    }),
    ("s3_read_write_resource", {
        "cfn_param_mapping": "S3ReadWriteResource",
    }),
    # Customization
    ("template_url", {
        # FIXME use UrlValidator in s3_validators
        # "validators": [url_validator],
        # Ignored during update since we force using previous template
    }),
    ("shared_dir", {
        "type": SharedDirCfnParam,
        "cfn_param_mapping": "SharedDir",
        "default": "/shared",
    }),
    ("enable_efa", {
        "allowed_values": ["compute"],  # does not apply to pcluster 3.0
        "cfn_param_mapping": "EFA",
    }),
    ("enable_efa_gdr", {
        "allowed_values": ["compute"],  # does not apply to pcluster 3.0
        "cfn_param_mapping": "EFAGDR",
    }),
    ("ephemeral_dir", {
        "default": "/scratch",
        "cfn_param_mapping": "EphemeralDir",
    }),
    ("encrypted_ephemeral", {
        "default": False,
        "type": BoolCfnParam,
        "cfn_param_mapping": "EncryptedEphemeral",
    }),
    ("custom_ami", {
        "cfn_param_mapping": "CustomAMI",
    }),
    ("pre_install", {
        "cfn_param_mapping": "PreInstallScript",
    }),
    ("pre_install_args", {
        "type": ArgsCfnParam,
        "cfn_param_mapping": "PreInstallArgs",
    }),
    ("post_install", {
        "cfn_param_mapping": "PostInstallScript",
    }),
    ("post_install_args", {
        "type": ArgsCfnParam,
        "cfn_param_mapping": "PostInstallArgs",
    }),
    ("extra_json", {
        "type": ExtraJsonCfnParam,
        "cfn_param_mapping": "ExtraJson",
    }),
    ("additional_cfn_template", {
        "cfn_param_mapping": "AdditionalCfnTemplate",
        # FIXME use UrlValidator in s3_validators
        # "validators": [url_validator],
    }),
    ("tags", {
        # There is no cfn_param_mapping because it's not converted to a CFN Input parameter
        "type": TagsParam,
    }),
    ("custom_chef_cookbook", {
        "cfn_param_mapping": "CustomChefCookbook",
    }),
    ("enable_intel_hpc_platform", {
        "default": False,
        "type": BoolCfnParam,
        "cfn_param_mapping": "IntelHPCPlatform",
    }),
    # Settings
    ("scaling_settings", {
        "type": SettingsCfnParam,
        "referred_section": SCALING,
    }),
    ("vpc_settings", {
        "type": SettingsCfnParam,
        "required": True,
        "referred_section": VPC,
    }),
    ("ebs_settings", {
        "type": EBSSettingsCfnParam,
        "referred_section": EBS,
    }),
    ("efs_settings", {
        "type": SettingsCfnParam,
        "referred_section": EFS,
    }),
    ("raid_settings", {
        "type": SettingsCfnParam,
        "referred_section": RAID,
    }),
    ("fsx_settings", {
        "type": SettingsCfnParam,
        "referred_section": FSX,
    }),
    ("dcv_settings", {
        "type": SettingsCfnParam,
        "referred_section": DCV,
    }),
    ("cw_log_settings", {
        "type": SettingsCfnParam,
        "referred_section": CW_LOG,
    }),
    ("dashboard_settings", {
        "type": SettingsJsonParam,
        "referred_section": DASHBOARD,
    }),
    # Moved from the "Access and Networking" section because its configuration is
    # dependent on multiple other parameters from within this section.
    ("additional_iam_policies", {
        "type": AdditionalIamPoliciesCfnParam,
        "cfn_param_mapping": "EC2IAMPolicies",
    }),
    # Derived parameters - present in CFN parameters but not in config file
    ("architecture", {
        "cfn_param_mapping": "Architecture",
        "visibility": Visibility.PRIVATE,
    }),
    ("hit_template_url", {
        # FIXME use UrlValidator in s3_validators
        # "validators": [url_validator],
    }),
    ("cw_dashboard_template_url", {
        # FIXME use UrlValidator in s3_validators
        # "validators": [url_validator],
    }),
    ("network_interfaces_count", {
        "type": NetworkInterfacesCountCfnParam,
        "default": ["1", "1"],
        "cfn_param_mapping": "NetworkInterfacesCount",
        # This param is managed automatically
        "visibility": Visibility.PRIVATE,
    }),
    ("cluster_resource_bucket", {
        "cfn_param_mapping": "ResourcesS3Bucket",
        "update_policy": UpdatePolicy.READ_ONLY_RESOURCE_BUCKET,
    }),
    ("iam_lambda_role", {
        "cfn_param_mapping": "IAMLambdaRoleName",
    }),
]


CLUSTER_SIT = {
    "type": ClusterCfnSection,
    "key": "cluster",
    "default_label": "default",
    "cluster_model": "SIT",
    "params": OrderedDict(
        CLUSTER_COMMON_PARAMS + [
            ("placement_group", {
                "cfn_param_mapping": "PlacementGroup",
            }),
            ("placement", {
                "default": "compute",
                "cfn_param_mapping": "Placement",
                "allowed_values": ["cluster", "compute"],  # does not apply to pcluster 3.0
            }),
            # Compute fleet
            ("compute_instance_type", {
                "type": ComputeInstanceTypeCfnParam,
                "cfn_param_mapping": "ComputeInstanceType",
            }),
            ("initial_queue_size", {
                "type": QueueSizeCfnParam,
                "default": 0,
                "cfn_param_mapping": "DesiredSize",  # TODO verify the update case
            }),
            ("max_queue_size", {
                "type": QueueSizeCfnParam,
                "default": 10,
                "cfn_param_mapping": "MaxSize",
            }),
            ("maintain_initial_size", {
                "type": MaintainInitialSizeCfnParam,
                "default": False,
                "cfn_param_mapping": "MinSize",
            }),
            ("min_vcpus", {
                "type": QueueSizeCfnParam,
                "default": 0,
                "cfn_param_mapping": "MinSize",
            }),
            ("desired_vcpus", {
                "type": QueueSizeCfnParam,
                "default": 4,
                "cfn_param_mapping": "DesiredSize",
                # Desired size is automatically managed during the update
            }),
            ("max_vcpus", {
                "type": QueueSizeCfnParam,
                "default": 10,
                "cfn_param_mapping": "MaxSize",
            }),
            ("cluster_type", {
                "default": "ondemand",
                "cfn_param_mapping": "ClusterType",
            }),
            ("spot_price", {
                "type": SpotPriceCfnParam,
                "default": 0,
                "cfn_param_mapping": "SpotPrice",
            }),
            ("spot_bid_percentage", {
                "type": SpotBidPercentageCfnParam,
                "default": 0,
                "cfn_param_mapping": "SpotPrice",
            }),
            ("disable_hyperthreading", {
                "type": DisableHyperThreadingCfnParam,
                "default": False,
                "cfn_param_mapping": "Cores",
            }),
        ]
    )
}


CLUSTER_HIT = {
    "type": ClusterCfnSection,
    "key": "cluster",
    "default_label": "default",
    "cluster_model": "HIT",
    "params": OrderedDict(
        CLUSTER_COMMON_PARAMS + [
            ("default_queue", {
                "type": DefaultComputeQueueJsonParam,
                # This param is managed automatically
                "visibility": Visibility.PRIVATE,
            }),
            ("queue_settings", {
                "type": SettingsJsonParam,
                "referred_section": QUEUE,
            }),
            ("disable_hyperthreading", {
                "type": DisableHyperThreadingCfnParam,
                "cfn_param_mapping": "Cores",
            }),
            ("disable_cluster_dns", {
                "type": BooleanJsonParam,
                "default": False,
            }),
        ]
    )
}

# fmt: on
