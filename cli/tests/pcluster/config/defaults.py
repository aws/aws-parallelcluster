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

from enum import Enum

# ------------------ Default internal representation values ------------------ #

DEFAULT_AWS_DICT = {"aws_access_key_id": None, "aws_secret_access_key": None, "aws_region_name": "us-east-1"}

DEFAULT_GLOBAL_DICT = {"cluster_template": "default", "update_check": True, "sanity_check": True}

DEFAULT_ALIASES_DICT = {"ssh": "ssh {CFN_USER}@{MASTER_IP} {ARGS}"}


DEFAULT_SCALING_DICT = {"scaledown_idletime": 10}

DEFAULT_VPC_DICT = {
    "vpc_id": None,
    "master_subnet_id": None,
    "ssh_from": "0.0.0.0/0",
    "additional_sg": None,
    "compute_subnet_id": None,
    "compute_subnet_cidr": None,
    "use_public_ips": True,
    "vpc_security_group_id": None,
    "master_availability_zone": None,
    "compute_availability_zone": None,
}

DEFAULT_EBS_DICT = {
    "shared_dir": None,
    "ebs_snapshot_id": None,
    "volume_type": "gp2",
    "volume_size": 20,
    "volume_iops": 100,
    "encrypted": False,
    "ebs_kms_key_id": None,
    "ebs_volume_id": None,
}

DEFAULT_EFS_DICT = {
    "shared_dir": None,
    "efs_fs_id": None,
    "performance_mode": "generalPurpose",
    "efs_kms_key_id": None,
    "provisioned_throughput": None,
    "encrypted": False,
    "throughput_mode": "bursting",
}

DEFAULT_RAID_DICT = {
    "shared_dir": None,
    "raid_type": None,
    "num_of_raid_volumes": None,
    "volume_type": "gp2",
    "volume_size": 20,
    "volume_iops": 100,
    "encrypted": False,
    "ebs_kms_key_id": None,
}

DEFAULT_FSX_DICT = {
    "shared_dir": None,
    "fsx_fs_id": None,
    "storage_capacity": None,
    "fsx_kms_key_id": None,
    "imported_file_chunk_size": None,
    "export_path": None,
    "import_path": None,
    "weekly_maintenance_start_time": None,
}

DEFAULT_DCV_DICT = {"enable": None, "port": 8443, "access_from": "0.0.0.0/0"}

DEFAULT_CLUSTER_DICT = {
    "key_name": None,
    "template_url": None,
    "base_os": "alinux",
    "scheduler": "sge",
    "shared_dir": "/shared",
    "placement_group": None,
    "placement": "compute",
    "master_instance_type": "t2.micro",
    "master_root_volume_size": 25,
    "compute_instance_type": "t2.micro",
    "compute_root_volume_size": 25,
    "initial_queue_size": 0,
    "max_queue_size": 10,
    "maintain_initial_size": False,
    "min_vcpus": 0,
    "desired_vcpus": 4,
    "max_vcpus": 10,
    "cluster_type": "ondemand",
    "spot_price": 0.0,
    "spot_bid_percentage": 0,
    "proxy_server": None,
    "ec2_iam_role": None,
    "additional_iam_policies": ["arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"],
    "s3_read_resource": None,
    "s3_read_write_resource": None,
    "enable_efa": None,
    "ephemeral_dir": "/scratch",
    "encrypted_ephemeral": False,
    "custom_ami": None,
    "pre_install": None,
    "pre_install_args": None,
    "post_install": None,
    "post_install_args": None,
    "extra_json": {},
    "additional_cfn_template": None,
    "tags": {},
    "custom_chef_cookbook": None,
    "custom_awsbatch_template_url": None,
    "disable_hyperthreading": False,
    "enable_intel_hpc_platform": False,
    "scaling_settings": "default",
    "vpc_settings": "default",
    "ebs_settings": None,
    "efs_settings": None,
    "raid_settings": None,
    "fsx_settings": None,
    "dcv_settings": None,
    "cw_log_settings": None,
}

DEFAULT_CW_LOG_DICT = {"enable": True, "retention_days": 14}

DEFAULT_PCLUSTER_DICT = {"cluster": DEFAULT_CLUSTER_DICT}


class DefaultDict(Enum):
    """Utility class to store default values for the internal dictionary representation of PclusterConfig sections."""

    aws = DEFAULT_AWS_DICT
    global_ = DEFAULT_GLOBAL_DICT
    aliases = DEFAULT_ALIASES_DICT
    cluster = DEFAULT_CLUSTER_DICT
    scaling = DEFAULT_SCALING_DICT
    vpc = DEFAULT_VPC_DICT
    ebs = DEFAULT_EBS_DICT
    efs = DEFAULT_EFS_DICT
    raid = DEFAULT_RAID_DICT
    fsx = DEFAULT_FSX_DICT
    dcv = DEFAULT_DCV_DICT
    cw_log = DEFAULT_CW_LOG_DICT
    pcluster = DEFAULT_PCLUSTER_DICT


# ------------------ Default CFN parameters ------------------ #

# number of CFN parameters created by the PclusterConfig object.
CFN_CONFIG_NUM_OF_PARAMS = 58

# CFN parameters created by the pcluster CLI
CFN_CLI_RESERVED_PARAMS = ["ResourcesS3Bucket"]


DEFAULT_SCALING_CFN_PARAMS = {"ScaleDownIdleTime": "10"}

DEFAULT_VPC_CFN_PARAMS = {
    "VPCId": "NONE",
    "MasterSubnetId": "NONE",
    "AccessFrom": "0.0.0.0/0",
    "AdditionalSG": "NONE",
    "ComputeSubnetId": "NONE",
    "ComputeSubnetCidr": "NONE",
    "UsePublicIps": "true",
    "VPCSecurityGroupId": "NONE",
    "AvailabilityZone": "NONE",
}

DEFAULT_EBS_CFN_PARAMS = {
    "SharedDir": "NONE,NONE,NONE,NONE,NONE",
    "EBSSnapshotId": "NONE,NONE,NONE,NONE,NONE",
    "VolumeType": "gp2,gp2,gp2,gp2,gp2",
    "VolumeSize": "20,20,20,20,20",
    "VolumeIOPS": "100,100,100,100,100",
    "EBSEncryption": "false,false,false,false,false",
    "EBSKMSKeyId": "NONE,NONE,NONE,NONE,NONE",
    "EBSVolumeId": "NONE,NONE,NONE,NONE,NONE",
}

DEFAULT_EFS_CFN_PARAMS = {"EFSOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE"}

DEFAULT_RAID_CFN_PARAMS = {"RAIDOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE"}

DEFAULT_FSX_CFN_PARAMS = {"FSXOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE"}

DEFAULT_DCV_CFN_PARAMS = {"DCVOptions": "NONE,NONE,NONE"}
DEFAULT_CW_LOG_CFN_PARAMS = {"CWLogOptions": "true,14"}

DEFAULT_CLUSTER_CFN_PARAMS = {
    "KeyName": "NONE",
    "BaseOS": "alinux",
    "CLITemplate": "default",
    "Scheduler": "sge",
    "SharedDir": "/shared",
    "PlacementGroup": "NONE",
    "Placement": "compute",
    "MasterInstanceType": "t2.micro",
    "MasterRootVolumeSize": "25",
    "ComputeInstanceType": "t2.micro",
    "ComputeRootVolumeSize": "25",
    "DesiredSize": "0",
    "MaxSize": "10",
    "MinSize": "0",
    "ClusterType": "ondemand",
    "SpotPrice": "0",
    "ProxyServer": "NONE",
    "EC2IAMRoleName": "NONE",
    "EC2IAMPolicies": "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
    "S3ReadResource": "NONE",
    "S3ReadWriteResource": "NONE",
    "EFA": "NONE",
    "EphemeralDir": "/scratch",
    "EncryptedEphemeral": "false",
    "CustomAMI": "NONE",
    "PreInstallScript": "NONE",
    "PreInstallArgs": "NONE",
    "PostInstallScript": "NONE",
    "PostInstallArgs": "NONE",
    "ExtraJson": "{}",
    "AdditionalCfnTemplate": "NONE",
    "CustomChefCookbook": "NONE",
    "CustomAWSBatchTemplateURL": "NONE",
    "NumberOfEBSVol": "1",
    "Cores": "-1,-1",
    "IntelHPCPlatform": "false",
    # "ResourcesS3Bucket": "NONE",  # parameter added by the CLI
    # scaling
    "ScaleDownIdleTime": "10",
    # vpc
    "VPCId": "NONE",
    "MasterSubnetId": "NONE",
    "AccessFrom": "0.0.0.0/0",
    "AdditionalSG": "NONE",
    "ComputeSubnetId": "NONE",
    "ComputeSubnetCidr": "NONE",
    "UsePublicIps": "true",
    "VPCSecurityGroupId": "NONE",
    "AvailabilityZone": "NONE",
    # ebs
    # "SharedDir": "NONE,NONE,NONE,NONE,NONE",  # not existing with single ebs volume
    "EBSSnapshotId": "NONE,NONE,NONE,NONE,NONE",
    "VolumeType": "gp2,gp2,gp2,gp2,gp2",
    "VolumeSize": "20,20,20,20,20",
    "VolumeIOPS": "100,100,100,100,100",
    "EBSEncryption": "false,false,false,false,false",
    "EBSKMSKeyId": "NONE,NONE,NONE,NONE,NONE",
    "EBSVolumeId": "NONE,NONE,NONE,NONE,NONE",
    # efs
    "EFSOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
    # raid
    "RAIDOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
    # fsx
    "FSXOptions": "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
    # dcv
    "DCVOptions": "NONE,NONE,NONE",
    # cw_log_settings
    "CWLogOptions": "true,14",
}


class DefaultCfnParams(Enum):
    """Utility class to store default values for CFN parameters."""

    scaling = DEFAULT_SCALING_CFN_PARAMS
    vpc = DEFAULT_VPC_CFN_PARAMS
    ebs = DEFAULT_EBS_CFN_PARAMS
    efs = DEFAULT_EFS_CFN_PARAMS
    raid = DEFAULT_RAID_CFN_PARAMS
    fsx = DEFAULT_FSX_CFN_PARAMS
    dcv = DEFAULT_DCV_CFN_PARAMS
    cw_log = DEFAULT_CW_LOG_CFN_PARAMS
    cluster = DEFAULT_CLUSTER_CFN_PARAMS
