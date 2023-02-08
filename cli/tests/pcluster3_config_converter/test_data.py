#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.


region_input_0 = """
[aws]
aws_region_name = us-east-1
"""

region_output_0 = """
Region: us-east-1
"""

region_input_1 = """
# region
[aws]
# region
aws_region_name =    us-east-2
"""

region_output_1 = """
Region: us-east-2
"""

region_test = [(region_input_0, region_output_0), (region_input_1, region_output_1)]

image_input_0 = """
[cluster default]
base_os = alinux2
custom_ami = ami-123
"""

image_output_0 = """
Image:
  CustomAmi: ami-123
  Os: alinux2
"""

image_input_1 = """
[cluster default]
base_os = alinux2
"""

image_output_1 = """
Image:
  Os: alinux2
"""

image_input_2 = """
[cluster default]
custom_ami = ami-123
"""

image_output_2 = """
Image:
  CustomAmi: ami-123
"""

image_test = [(image_input_0, image_output_0), (image_input_1, image_output_1), (image_input_2, image_output_2)]

iam_region_0 = "us-west-1"

iam_input_0 = """
[cluster default]
iam_lambda_role = role_name
"""

iam_output_0 = """
Iam:
  Role:
    LambdaFunctionRole: arn:aws:iam::1234567:role/role_name
"""

iam_region_1 = "cn-north-1"

iam_input_1 = """
[cluster default]
iam_lambda_role = role_name
iam_lambda_role1 =
"""

iam_output_1 = """
Iam:
  Role:
    LambdaFunctionRole: arn:aws-cn:iam::1234567:role/role_name
"""

iam_region_2 = "us-iso-east-1"

iam_input_2 = """
[cluster default]
iam_lambda_role = role_name
iam_lambda_role1 =
"""

iam_output_2 = """
Iam:
  Role:
    LambdaFunctionRole: arn:aws-iso:iam::1234567:role/role_name
"""

iam_region_3 = "us-isob-east-1"

iam_input_3 = """
[cluster default]
iam_lambda_role = role_name
iam_lambda_role1 =
"""

iam_output_3 = """
Iam:
  Role:
    LambdaFunctionRole: arn:aws-iso-b:iam::1234567:role/role_name
"""

iam_test = [
    (iam_region_0, iam_input_0, iam_output_0),
    (iam_region_1, iam_input_1, iam_output_1),
    (iam_region_2, iam_input_2, iam_output_2),
    (iam_region_3, iam_input_3, iam_output_3),
]

additional_packages_input_0 = """
[cluster default]
enable_intel_hpc_platform = True
"""

additional_packages_output_0 = """
AdditionalPackages:
  IntelSoftware:
    IntelHpcPlatform: True
"""

additional_packages_input_1 = """
[cluster default]
enable_intel_hpc_platform = False
"""

additional_packages_output_1 = """
AdditionalPackages:
  IntelSoftware:
    IntelHpcPlatform: False
"""

additional_packages_test = [
    (additional_packages_input_0, additional_packages_output_0),
    (additional_packages_input_1, additional_packages_output_1),
]

tags_input_0 = """
[cluster default]
tags = {"key": "value", "key2": "value2"}
"""

tags_output_0 = """
Tags:
  - Key: key
    Value: value
  - Key: key2
    Value: value2
"""

tags_input_1 = """
[cluster default]
tags = {"key": "value"}
"""

tags_output_1 = """
Tags:
  - Key: key
    Value: value
"""

tags_input_2 = """
[cluster default]
tags = key
"""

tags_output_2 = """
"""

tags_error_2 = "Tags should be in the format of dictionary"

tags_test = [
    (tags_input_0, tags_output_0, None),
    (tags_input_1, tags_output_1, None),
    (tags_input_2, tags_output_2, tags_error_2),
]

monitoring_input_0 = """
[cluster default]
cw_log_settings = default
dashboard_settings = default

[cw_log default]
enable = True
retention_days = 10

[dashboard default]
enable = False

[dashboard default1]
enable = True
"""

monitoring_output_0 = """
Monitoring:
  Dashboards:
    CloudWatch:
      Enabled: False
  Logs:
    CloudWatch:
      Enabled: True
      RetentionInDays: 10
"""

monitoring_input_1 = """
[cluster default]
cw_log_settings = default

[cw_log default]
enable = True
retention_days = 10
"""

monitoring_output_1 = """
Monitoring:
  Logs:
    CloudWatch:
      Enabled: True
      RetentionInDays: 10
"""

monitoring_input_2 = """
[cluster default]
dashboard_settings = default

[cw_log default]
enable = True
retention_days = 10

[dashboard default]
enable = True
"""

monitoring_output_2 = """
Monitoring:
  Dashboards:
    CloudWatch:
      Enabled: True
"""

monitoring_input_3 = """
[cluster default]
cw_log_settings = default
dashboard_settings = default

[dashboard default]
enable = False
"""

monitoring_output_3 = """
Monitoring:
  Dashboards:
    CloudWatch:
      Enabled: False
"""

monitoring_test = [
    (monitoring_input_0, monitoring_output_0),
    (monitoring_input_1, monitoring_output_1),
    (monitoring_input_2, monitoring_output_2),
    (monitoring_input_3, monitoring_output_3),
]

custom_s3_bucket_test_input_0 = """
[cluster default]
cluster_resource_bucket = testbucket_123
"""

custom_s3_bucket_test_output_0 = """
CustomS3Bucket: testbucket_123
"""

convert_custom_s3_bucket_test = [(custom_s3_bucket_test_input_0, custom_s3_bucket_test_output_0)]

convert_additional_resources_test_input_0 = """
[cluster default]
additional_cfn_template = https://<bucket-name>.s3.amazonaws.com/my-cfn-template.yaml
"""

convert_additional_resources_test_output_0 = """
AdditionalResources: https://<bucket-name>.s3.amazonaws.com/my-cfn-template.yaml
"""

convert_additional_resources_test = [
    (convert_additional_resources_test_input_0, convert_additional_resources_test_output_0)
]

convert_dev_settings_test_input_0 = """
[cluster default]
extra_json = https://<bucket-name>.s3.amazonaws.com/my-cfn-template.yaml
custom_chef_cookbook = https://chef-cookbook
template_url = https://template-url
instance_types_data =  {"hpc": {"InstanceType": "hpc", "CurrentGeneration": true, "FreeTierEligible": false, "SupportedUsageClasses": ["on-demand", "spot"], "SupportedRootDeviceTypes": ["ebs"], "SupportedVirtualizationTypes": ["hvm"], "BareMetal": true, "ProcessorInfo": {"SupportedArchitectures": ["x86_64"], "SustainedClockSpeedInGhz": 3.6}, "VCpuInfo": {"DefaultVCpus": 96}, "MemoryInfo": {"SizeInMiB": 196608}, "InstanceStorageSupported": false, "EbsInfo": {"EbsOptimizedSupport": "default", "EncryptionSupport": "supported", "EbsOptimizedInfo": {"BaselineBandwidthInMbps": 19000, "BaselineThroughputInMBps": 2375, "BaselineIops": 80000, "MaximumBandwidthInMbps": 19000, "MaximumThroughputInMBps": 2375, "MaximumIops": 80000}, "NvmeSupport": "unsupported"}, "NetworkInfo": {"NetworkPerformance": "25 Gigabit", "MaximumNetworkInterfaces": 15, "MaximumNetworkCards": 1, "DefaultNetworkCardIndex": 0, "NetworkCards": [{"NetworkCardIndex": 0, "NetworkPerformance": "25 Gigabit", "MaximumNetworkInterfaces": 15}], "Ipv4AddressesPerInterface": 50, "Ipv6AddressesPerInterface": 50, "Ipv6Supported": true, "EnaSupport": "required", "EfaSupported": true}, "PlacementGroupInfo": {"SupportedStrategies": ["cluster", "partition", "spread"]}, "HibernationSupported": false, "BurstablePerformanceSupported": false, "DedicatedHostsSupported": false, "AutoRecoverySupported": true}}
"""

convert_dev_settings_test_output_0 = """
DevSettings:
    InstanceTypesData: '{"hpc": {"InstanceType": "hpc", "CurrentGeneration": true, "FreeTierEligible": false, "SupportedUsageClasses": ["on-demand", "spot"], "SupportedRootDeviceTypes": ["ebs"], "SupportedVirtualizationTypes": ["hvm"], "BareMetal": true, "ProcessorInfo": {"SupportedArchitectures": ["x86_64"], "SustainedClockSpeedInGhz": 3.6}, "VCpuInfo": {"DefaultVCpus": 96}, "MemoryInfo": {"SizeInMiB": 196608}, "InstanceStorageSupported": false, "EbsInfo": {"EbsOptimizedSupport": "default", "EncryptionSupport": "supported", "EbsOptimizedInfo": {"BaselineBandwidthInMbps": 19000, "BaselineThroughputInMBps": 2375, "BaselineIops": 80000, "MaximumBandwidthInMbps": 19000, "MaximumThroughputInMBps": 2375, "MaximumIops": 80000}, "NvmeSupport": "unsupported"}, "NetworkInfo": {"NetworkPerformance": "25 Gigabit", "MaximumNetworkInterfaces": 15, "MaximumNetworkCards": 1, "DefaultNetworkCardIndex": 0, "NetworkCards": [{"NetworkCardIndex": 0, "NetworkPerformance": "25 Gigabit", "MaximumNetworkInterfaces": 15}], "Ipv4AddressesPerInterface": 50, "Ipv6AddressesPerInterface": 50, "Ipv6Supported": true, "EnaSupport": "required", "EfaSupported": true}, "PlacementGroupInfo": {"SupportedStrategies": ["cluster", "partition", "spread"]}, "HibernationSupported": false, "BurstablePerformanceSupported": false, "DedicatedHostsSupported": false, "AutoRecoverySupported": true}}'
    ClusterTemplate: https://template-url
    Cookbook:
        ExtraChefAttributes: https://<bucket-name>.s3.amazonaws.com/my-cfn-template.yaml
        ChefCookbook: https://chef-cookbook
"""

convert_dev_settings_test_input_1 = """
[cluster default]
custom_chef_cookbook = https://chef-cookbook
template_url = https://template-url
"""

convert_dev_settings_test_output_1 = """
DevSettings:
    ClusterTemplate: https://template-url
    Cookbook:
        ChefCookbook: https://chef-cookbook
"""
convert_dev_settings_test_input_2 = """
[cluster default]
extra_json = https://<bucket-name>.s3.amazonaws.com/my-cfn-template.yaml
instance_types_data =  {"hpc": {"InstanceType": "hpc", "CurrentGeneration": true, "FreeTierEligible": false, "SupportedUsageClasses": ["on-demand", "spot"], "SupportedRootDeviceTypes": ["ebs"], "SupportedVirtualizationTypes": ["hvm"], "BareMetal": true, "ProcessorInfo": {"SupportedArchitectures": ["x86_64"], "SustainedClockSpeedInGhz": 3.6}, "VCpuInfo": {"DefaultVCpus": 96}, "MemoryInfo": {"SizeInMiB": 196608}, "InstanceStorageSupported": false, "EbsInfo": {"EbsOptimizedSupport": "default", "EncryptionSupport": "supported", "EbsOptimizedInfo": {"BaselineBandwidthInMbps": 19000, "BaselineThroughputInMBps": 2375, "BaselineIops": 80000, "MaximumBandwidthInMbps": 19000, "MaximumThroughputInMBps": 2375, "MaximumIops": 80000}, "NvmeSupport": "unsupported"}, "NetworkInfo": {"NetworkPerformance": "25 Gigabit", "MaximumNetworkInterfaces": 15, "MaximumNetworkCards": 1, "DefaultNetworkCardIndex": 0, "NetworkCards": [{"NetworkCardIndex": 0, "NetworkPerformance": "25 Gigabit", "MaximumNetworkInterfaces": 15}], "Ipv4AddressesPerInterface": 50, "Ipv6AddressesPerInterface": 50, "Ipv6Supported": true, "EnaSupport": "required", "EfaSupported": true}, "PlacementGroupInfo": {"SupportedStrategies": ["cluster", "partition", "spread"]}, "HibernationSupported": false, "BurstablePerformanceSupported": false, "DedicatedHostsSupported": false, "AutoRecoverySupported": true}}
"""

convert_dev_settings_test_output_2 = """
DevSettings:
    InstanceTypesData: '{"hpc": {"InstanceType": "hpc", "CurrentGeneration": true, "FreeTierEligible": false, "SupportedUsageClasses": ["on-demand", "spot"], "SupportedRootDeviceTypes": ["ebs"], "SupportedVirtualizationTypes": ["hvm"], "BareMetal": true, "ProcessorInfo": {"SupportedArchitectures": ["x86_64"], "SustainedClockSpeedInGhz": 3.6}, "VCpuInfo": {"DefaultVCpus": 96}, "MemoryInfo": {"SizeInMiB": 196608}, "InstanceStorageSupported": false, "EbsInfo": {"EbsOptimizedSupport": "default", "EncryptionSupport": "supported", "EbsOptimizedInfo": {"BaselineBandwidthInMbps": 19000, "BaselineThroughputInMBps": 2375, "BaselineIops": 80000, "MaximumBandwidthInMbps": 19000, "MaximumThroughputInMBps": 2375, "MaximumIops": 80000}, "NvmeSupport": "unsupported"}, "NetworkInfo": {"NetworkPerformance": "25 Gigabit", "MaximumNetworkInterfaces": 15, "MaximumNetworkCards": 1, "DefaultNetworkCardIndex": 0, "NetworkCards": [{"NetworkCardIndex": 0, "NetworkPerformance": "25 Gigabit", "MaximumNetworkInterfaces": 15}], "Ipv4AddressesPerInterface": 50, "Ipv6AddressesPerInterface": 50, "Ipv6Supported": true, "EnaSupport": "required", "EfaSupported": true}, "PlacementGroupInfo": {"SupportedStrategies": ["cluster", "partition", "spread"]}, "HibernationSupported": false, "BurstablePerformanceSupported": false, "DedicatedHostsSupported": false, "AutoRecoverySupported": true}}'
    Cookbook:
        ExtraChefAttributes: https://<bucket-name>.s3.amazonaws.com/my-cfn-template.yaml
"""

convert_dev_settings_test = [
    (convert_dev_settings_test_input_0, convert_dev_settings_test_output_0),
    (convert_dev_settings_test_input_1, convert_dev_settings_test_output_1),
    (convert_dev_settings_test_input_2, convert_dev_settings_test_output_2),
]

shared_storage_input_0 = """
[cluster default]
ebs_settings = custom1,     custom2
raid_settings = custom3
efs_settings = customfs
fsx_settings = fs

[ebs custom1]
shared_dir = /shared_dir1
volume_type = gp2
encrypted = false

[ebs custom2]
shared_dir = /shared_dir1
volume_type = gp2

[raid custom3]
shared_dir = /shared_dir1
volume_type = gp2
num_of_raid_volumes = 2
raid_type = 0

[efs customfs]
shared_dir = efs
encrypted = false
performance_mode = generalPurpose
efs_fs_id = fs-12345
efs_kms_key_id = 1234abcd-12ab-34cd-56ef-1234567890ab
provisioned_throughput = 1024
throughput_mode = provisioned

[fsx fs]
shared_dir = /fsx
storage_capacity = 3600
fsx_kms_key_id = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
per_unit_storage_throughput = 200
storage_type = SSD
drive_cache_type = READ
data_compression_type = LZ4
"""

shared_storage_output_0 = """
SharedStorage:
  - EbsSettings:
      Encrypted: false
      VolumeType: gp2
    MountDir: /shared_dir1
    Name: custom1
    StorageType: Ebs
  - EbsSettings:
      VolumeType: gp2
    MountDir: /shared_dir1
    Name: custom2
    StorageType: Ebs
  - EbsSettings:
      Raid:
        NumberOfVolumes: 2
        Type: 0
      VolumeType: gp2
    MountDir: /shared_dir1
    Name: custom3
    StorageType: Ebs
  - EfsSettings:
      Encrypted: false
      FileSystemId: fs-12345
      KmsKeyId: 1234abcd-12ab-34cd-56ef-1234567890ab
      PerformanceMode: generalPurpose
      ProvisionedThroughput: 1024
      ThroughputMode: provisioned
    MountDir: efs
    Name: customfs
    StorageType: Efs
  - FsxLustreSettings:
      DataCompressionType: LZ4
      DriveCacheType: READ
      KmsKeyId: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
      PerUnitStorageThroughput: 200
      StorageCapacity: 3600
      StorageType: SSD
    MountDir: /fsx
    Name: fs
    StorageType: FsxLustre
"""

shared_storage_input_1 = """
[cluster default]
ebs_settings = custom1 ,     custom2
raid_settings = custom3
efs_settings = customfs
fsx_settings = fs

[ebs custom1]
shared_dir = /shared_dir1
volume_type = gp2
encrypted = true
volume_size = 25
ebs_snapshot_id = snap-123
ebs_kms_key_id = alias/my-key


[ebs custom2]
shared_dir = /shared_dir2
volume_type = gp3
ebs_volume_id = vol-123
volume_iops = 200

[raid custom3]
shared_dir = /shared_dir3
volume_type = gp2
num_of_raid_volumes = 2
volume_size = 20
volume_iops = 300
ebs_kms_key_id = alias/my-key
raid_type = 1

[efs customfs]
shared_dir = efs
encrypted = false
performance_mode = generalPurpose
efs_fs_id = fs-12345
efs_kms_key_id = 1234abcd-12ab-34cd-56ef-1234567890ab
provisioned_throughput = 1024
throughput_mode = provisioned

[fsx fs]
shared_dir = /fsx
storage_capacity = 3600
imported_file_chunk_size = 1024
export_path = s3://bucket/folder
import_path = s3://bucket
weekly_maintenance_start_time = 1:00:00
fsx_fs_id = fs-073c3803dca3e28a6
automatic_backup_retention_days = 35
copy_tags_to_backups = true
daily_automatic_backup_start_time = 01:03
deployment_type = SCRATCH_2
fsx_backup_id = backup-fedcba98
fsx_kms_key_id = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
per_unit_storage_throughput = 200
storage_type = SSD
drive_cache_type = READ
auto_import_policy = NEW_CHANGED
"""

shared_storage_output_1 = """
SharedStorage:
  - EbsSettings:
      Encrypted: true
      KmsKeyId: alias/my-key
      Size: 25
      SnapshotId: snap-123
      VolumeType: gp2
    MountDir: /shared_dir1
    Name: custom1
    StorageType: Ebs
  - EbsSettings:
      Iops: 200
      VolumeId: vol-123
      VolumeType: gp3
    MountDir: /shared_dir2
    Name: custom2
    StorageType: Ebs
  - EbsSettings:
      Iops: 300
      KmsKeyId: alias/my-key
      Raid:
        NumberOfVolumes: 2
        Type: 1
      Size: 20
      VolumeType: gp2
    MountDir: /shared_dir3
    Name: custom3
    StorageType: Ebs
  - EfsSettings:
      Encrypted: false
      FileSystemId: fs-12345
      KmsKeyId: 1234abcd-12ab-34cd-56ef-1234567890ab
      PerformanceMode: generalPurpose
      ProvisionedThroughput: 1024
      ThroughputMode: provisioned
    MountDir: efs
    Name: customfs
    StorageType: Efs
  - FsxLustreSettings:
      AutoImportPolicy: NEW_CHANGED
      AutomaticBackupRetentionDays: 35
      BackupId: backup-fedcba98
      CopyTagsToBackups: true
      DailyAutomaticBackupStartTime: 01:03
      DeploymentType: SCRATCH_2
      DriveCacheType: READ
      ExportPath: s3://bucket/folder
      FileSystemId: fs-073c3803dca3e28a6
      ImportPath: s3://bucket
      ImportedFileChunkSize: 1024
      KmsKeyId: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
      PerUnitStorageThroughput: 200
      StorageCapacity: 3600
      StorageType: SSD
      WeeklyMaintenanceStartTime: '1:00:00'
    MountDir: /fsx
    Name: fs
    StorageType: FsxLustre
"""

shared_storage_input_2 = """
[cluster default]
ebs_settings = custom1 ,     custom2, custom3, custom4, custom5

[ebs custom1]
shared_dir = /shared_dir1
volume_type = gp2
encrypted = true
volume_size = 25
ebs_snapshot_id = snap-123
ebs_kms_key_id = alias/my-key

[ebs custom2]
shared_dir = /shared_dir2
volume_type = gp3
ebs_volume_id = vol-123
volume_iops = 200

[ebs custom3]
shared_dir = /shared_dir3
volume_type = io2
ebs_volume_id = vol-123
volume_iops = 200
volume_throughput = 300

[ebs custom4]
shared_dir = /shared_dir4
volume_type = io1
ebs_volume_id = vol-123
volume_iops = 200
encrypted = false

[ebs custom5]
shared_dir = /shared_dir5
volume_type = st1
ebs_volume_id = vol-123
volume_iops = 200
"""

shared_storage_output_2 = """
SharedStorage:
  - EbsSettings:
      Encrypted: true
      KmsKeyId: alias/my-key
      Size: 25
      SnapshotId: snap-123
      VolumeType: gp2
    MountDir: /shared_dir1
    Name: custom1
    StorageType: Ebs
  - EbsSettings:
      Iops: 200
      VolumeId: vol-123
      VolumeType: gp3
    MountDir: /shared_dir2
    Name: custom2
    StorageType: Ebs
  - EbsSettings:
      Iops: 200
      VolumeId: vol-123
      VolumeType: io2
      Throughput: 300
    MountDir: /shared_dir3
    Name: custom3
    StorageType: Ebs
  - EbsSettings:
      Iops: 200
      VolumeId: vol-123
      VolumeType: io1
      Encrypted: False
    MountDir: /shared_dir4
    Name: custom4
    StorageType: Ebs
  - EbsSettings:
      Iops: 200
      VolumeId: vol-123
      VolumeType: st1
    MountDir: /shared_dir5
    Name: custom5
    StorageType: Ebs
"""

shared_storage_input_3 = """
[cluster default]
ebs_settings = custom1
shared_dir = /shared_dir1

[ebs custom1]
volume_type = gp2
"""

shared_storage_output_3 = """
SharedStorage:
  - EbsSettings:
      VolumeType: gp2
    MountDir: /shared_dir1
    Name: custom1
    StorageType: Ebs
"""

shared_storage_input_4 = """
[cluster default]
shared_dir = /shared_dir1

"""

shared_storage_output_4 = """
SharedStorage:
  - MountDir: /shared_dir1
    Name: default-ebs
    StorageType: Ebs
"""
shared_storage_input_5 = """
[cluster default]
"""

shared_storage_output_5 = """
SharedStorage:
  - MountDir: /shared
    Name: default-ebs
    StorageType: Ebs
"""

shared_storage_test = [
    (shared_storage_input_0, shared_storage_output_0),
    (shared_storage_input_1, shared_storage_output_1),
    (shared_storage_input_2, shared_storage_output_2),
    (shared_storage_input_3, shared_storage_output_3),
    (shared_storage_input_4, shared_storage_output_4),
    (shared_storage_input_5, shared_storage_output_5),
]

headnode_input_0 = """
[cluster default]
pre_install = s3://testbucket/pre_install.sh
pre_install_args = 'R curl wget'
post_install = s3://testbucket/post_install.sh
post_install_args = "R curl wget"
dcv_settings = custom-dcv
ec2_iam_role = role_name
s3_read_resource = *
s3_read_write_resource = arn:aws:s3:::test/hello/*
master_instance_type = c5.xlarge
ephemeral_dir = /test
encrypted_ephemeral = true
vpc_settings = default
proxy_server = https://x.x.x.x:8080
key_name = key1
master_root_volume_size = 35
disable_hyperthreading = true

[dcv custom-dcv]
enable = master
port = 8443
access_from = 0.0.0.0/0

[vpc default]
vpc_id = vpc-0e0f223cc35256b9a
master_subnet_id = subnet-0bfad12f6b586686c
vpc_security_group_id = sg-xxxxxx
additional_sg = sg-xxxxxx
ssh_from = string
use_public_ips = false
"""

headnode_output_0 = """
HeadNode:
  DisableSimultaneousMultithreading: True
  CustomActions:
    OnNodeConfigured:
      Args:
        - s3://testbucket/post_install.sh
        - R
        - curl
        - wget
      Script: s3://testbucket/post_install.sh
    OnNodeStart:
      Args:
        - s3://testbucket/pre_install.sh
        - R
        - curl
        - wget
      Script: s3://testbucket/pre_install.sh
  Dcv:
    AllowedIps: 0.0.0.0/0
    Enabled: True
    Port: 8443
  Iam:
    InstanceRole: arn:aws:iam::1234567:role/role_name
    S3Access:
      - BucketName: '*'
      - BucketName: test
        EnableWriteAccess: true
        KeyName: hello/*
  InstanceType: c5.xlarge
  LocalStorage:
    EphemeralVolume:
      MountDir: /test
    RootVolume:
      Size: 35
  Networking:
    ElasticIp: False
    AdditionalSecurityGroups:
      - sg-xxxxxx
    Proxy:
      HttpProxyAddress: https://x.x.x.x:8080
    SecurityGroups:
      - sg-xxxxxx
    SubnetId: subnet-0bfad12f6b586686c
  Ssh:
    AllowedIps: string
    KeyName: key1
"""

headnode_input_1 = """
[cluster default]
pre_install = s3://testbucket/pre_install.sh
post_install = s3://testbucket/post_install.sh
dcv_settings = custom-dcv
s3_read_resource = arn:aws:s3:::*
s3_read_write_resource = arn:aws:s3:::test*
master_instance_type = c5.xlarge
vpc_settings = default
key_name = key1
master_root_volume_size = 35
additional_iam_policies = arn:aws:s3:::*,  arn:aws:ec2:::*

[dcv custom-dcv]
enable = master
port = 8443
access_from = 0.0.0.0/0

[vpc default]
vpc_id = vpc-0e0f223cc35256b9a
master_subnet_id = subnet-0bfad12f6b586686c
vpc_security_group_id = sg-xxxxxx
additional_sg = sg-xxxxxx
"""

headnode_output_1 = """
HeadNode:
  CustomActions:
    OnNodeConfigured:
      Script: s3://testbucket/post_install.sh
    OnNodeStart:
      Script: s3://testbucket/pre_install.sh
  Dcv:
    AllowedIps: 0.0.0.0/0
    Enabled: True
    Port: 8443
  Iam:
    S3Access:
      - BucketName: '*'
      - BucketName: test
        EnableWriteAccess: true
    AdditionalIamPolicies:
      - Policy: arn:aws:s3:::*
      - Policy: arn:aws:ec2:::*
  InstanceType: c5.xlarge
  LocalStorage:
    RootVolume:
      Size: 35
  Networking:
    AdditionalSecurityGroups:
      - sg-xxxxxx
    SecurityGroups:
      - sg-xxxxxx
    SubnetId: subnet-0bfad12f6b586686c
  Ssh:
    KeyName: key1
"""

headnode_input_2 = """
[cluster default]
master_instance_type = c5.xlarge
vpc_settings = default
key_name = key1
scheduler = awsbatch

[vpc default]
vpc_id = vpc-0e0f223cc35256b9a
master_subnet_id = subnet-0bfad12f6b586686c
"""

headnode_output_2 = """
HeadNode:
  InstanceType: c5.xlarge
  Networking:
    SubnetId: subnet-0bfad12f6b586686c
  Ssh:
    KeyName: key1
  Imds:
    Secured: False
"""

headnode_test = [
    (headnode_input_0, headnode_output_0),
    (headnode_input_1, headnode_output_1),
    (headnode_input_2, headnode_output_2),
]

slurm_input_0 = """
[cluster default]
pre_install = s3://testbucket/pre_install.sh
pre_install_args = 'R curl wget'
post_install = s3://testbucket/post_install.sh
post_install_args = "R curl wget"
ec2_iam_role = role_name
s3_read_resource = arn:aws:s3:::testbucket/*
s3_read_write_resource = arn:aws:s3:::test/hello/*
vpc_settings = default
proxy_server = https://x.x.x.x:8080
key_name = key1
queue_settings = queue1, queue2
scaling_settings = custom
scheduler = slurm
disable_cluster_dns = true
compute_root_volume_size = 40

[vpc default]
vpc_id = vpc-0e0f223cc35256b9a
master_subnet_id = subnet-0bfad12f6b586686c
vpc_security_group_id = sg-xxxxxx
additional_sg = sg-xxxxxx
ssh_from = string

[queue queue1]
compute_resource_settings = ondemand-i1,  ondemand-i3
disable_hyperthreading = true
enable_efa = true
enable_efa_gdr = false
placement_group = DYNAMIC

[queue queue2]
compute_resource_settings = ondemand-i2
placement_group = placement_group_id
compute_type = spot

[compute_resource ondemand-i1]
instance_type = c5.large
min_count = 1

[compute_resource ondemand-i3]
instance_type = c5.xlarge
min_count = 1
spot_price =5.88

[compute_resource ondemand-i2]
instance_type = c4.large
min_count = 2
max_count = 5

[scaling custom]
scaledown_idletime = 10
"""

slurm_output_0 = """
Scheduling:
  Scheduler: slurm
  SlurmQueues:
    - ComputeResources:
        - DisableSimultaneousMultithreading: true
          Efa:
            Enabled: true
            GdrSupport: false
          InstanceType: c5.large
          MinCount: 1
          Name: ondemand-i1
        - DisableSimultaneousMultithreading: true
          Efa:
            Enabled: true
            GdrSupport: false
          InstanceType: c5.xlarge
          MinCount: 1
          Name: ondemand-i3
          SpotPrice: 5.88
      CustomActions:
        OnNodeConfigured:
          Args:
            - s3://testbucket/post_install.sh
            - R
            - curl
            - wget
          Script: s3://testbucket/post_install.sh
        OnNodeStart:
          Args:
            - s3://testbucket/pre_install.sh
            - R
            - curl
            - wget
          Script: s3://testbucket/pre_install.sh
      Iam:
        InstanceRole: arn:aws:iam::1234567:role/role_name
        S3Access:
          - BucketName: testbucket
          - BucketName: test
            EnableWriteAccess: true
            KeyName: hello/*
      Name: queue1
      ComputeSettings:
        LocalStorage:
          RootVolume:
            Size: 40
      Networking:
        AdditionalSecurityGroups:
          - sg-xxxxxx
        PlacementGroup:
          Enabled: true
        Proxy:
          HttpProxyAddress: https://x.x.x.x:8080
        SecurityGroups:
          - sg-xxxxxx
        SubnetIds:
          - subnet-0bfad12f6b586686c
    - CapacityType: SPOT
      ComputeResources:
        - InstanceType: c4.large
          MaxCount: 5
          MinCount: 2
          Name: ondemand-i2
      CustomActions:
        OnNodeConfigured:
          Args:
            - s3://testbucket/post_install.sh
            - R
            - curl
            - wget
          Script: s3://testbucket/post_install.sh
        OnNodeStart:
          Args:
            - s3://testbucket/pre_install.sh
            - R
            - curl
            - wget
          Script: s3://testbucket/pre_install.sh
      Iam:
        InstanceRole: arn:aws:iam::1234567:role/role_name
        S3Access:
          - BucketName: testbucket
          - BucketName: test
            EnableWriteAccess: true
            KeyName: hello/*
      Name: queue2
      ComputeSettings:
        LocalStorage:
          RootVolume:
            Size: 40
      Networking:
        AdditionalSecurityGroups:
          - sg-xxxxxx
        PlacementGroup:
          Id: placement_group_id
        Proxy:
          HttpProxyAddress: https://x.x.x.x:8080
        SecurityGroups:
          - sg-xxxxxx
        SubnetIds:
          - subnet-0bfad12f6b586686c
  SlurmSettings:
    Dns:
      DisableManagedDns: true
    ScaledownIdletime: 10
"""

slurm_input_1 = """
[cluster default]
ec2_iam_role = role_name
s3_read_resource = arn:aws:s3:::testbucket*
s3_read_write_resource = arn:aws:s3:::test/hello/*
vpc_settings = default
proxy_server = https://x.x.x.x:8080
key_name = key1
queue_settings = queue1, queue2
scaling_settings = custom
scheduler = slurm
disable_cluster_dns = false

[vpc default]
vpc_id = vpc-0e0f223cc35256b9a
master_subnet_id = subnet-0bfad12f6b586686c
compute_subnet_id = subnet-12345
vpc_security_group_id = sg-xxxxxx
additional_sg = sg-xxxxxx
ssh_from = string

[queue queue1]
compute_resource_settings = ondemand-i1,  ondemand-i3
disable_hyperthreading = false
enable_efa = true
enable_efa_gdr = false
placement_group = DYNAMIC

[queue queue2]
compute_resource_settings = ondemand-i2
placement_group = placement_group_id
compute_type = spot
disable_hyperthreading = true

[compute_resource ondemand-i1]
instance_type = c5.large

[compute_resource ondemand-i3]
instance_type = c5.xlarge
min_count = 1
initial_count = 1
spot_price =5.88

[compute_resource ondemand-i2]
instance_type = c4.large

[scaling custom]
scaledown_idletime = 3
"""

slurm_output_1 = """
Scheduling:
  Scheduler: slurm
  SlurmQueues:
    - ComputeResources:
        - DisableSimultaneousMultithreading: false
          Efa:
            Enabled: true
            GdrSupport: false
          InstanceType: c5.large
          Name: ondemand-i1
        - DisableSimultaneousMultithreading: false
          Efa:
            Enabled: true
            GdrSupport: false
          InstanceType: c5.xlarge
          MinCount: 1
          Name: ondemand-i3
          SpotPrice: 5.88
      Iam:
        InstanceRole: arn:aws:iam::1234567:role/role_name
        S3Access:
          - BucketName: testbucket
          - BucketName: test
            EnableWriteAccess: true
            KeyName: hello/*
      Name: queue1
      Networking:
        AdditionalSecurityGroups:
          - sg-xxxxxx
        PlacementGroup:
          Enabled: true
        Proxy:
          HttpProxyAddress: https://x.x.x.x:8080
        SecurityGroups:
          - sg-xxxxxx
        SubnetIds:
          - subnet-12345
    - CapacityType: SPOT
      ComputeResources:
        - InstanceType: c4.large
          Name: ondemand-i2
          DisableSimultaneousMultithreading: true
      Iam:
        InstanceRole: arn:aws:iam::1234567:role/role_name
        S3Access:
          - BucketName: testbucket
          - BucketName: test
            EnableWriteAccess: true
            KeyName: hello/*
      Name: queue2
      Networking:
        AdditionalSecurityGroups:
          - sg-xxxxxx
        PlacementGroup:
          Id: placement_group_id
        Proxy:
          HttpProxyAddress: https://x.x.x.x:8080
        SecurityGroups:
          - sg-xxxxxx
        SubnetIds:
          - subnet-12345
  SlurmSettings:
    Dns:
      DisableManagedDns: false
    ScaledownIdletime: 3
"""

slurm_input_2 = """
[cluster default]
vpc_settings = default
key_name = key1
queue_settings = queue1
scheduler = slurm

[vpc default]
vpc_id = vpc-0e0f223cc35256b9a
master_subnet_id = subnet-0bfad12f6b586686c
compute_subnet_id = subnet-12345

[queue queue1]
compute_resource_settings = ondemand-i1

[compute_resource ondemand-i1]
instance_type = c5.large

"""

slurm_output_2 = """
Scheduling:
  Scheduler: slurm
  SlurmQueues:
    - ComputeResources:
        - InstanceType: c5.large
          Name: ondemand-i1
      Name: queue1
      Networking:
        SubnetIds:
          - subnet-12345
"""

awsabtch_input_0 = """
[cluster default]
vpc_settings = default
key_name = key1
scheduler = awsbatch
min_vcpus = 0
desired_vcpus = 4
max_vcpus = 20
spot_bid_percentage = 85
cluster_type = ondemand
compute_instance_type = optimal

[vpc default]
vpc_id = vpc-0e0f223cc35256b9a
master_subnet_id = subnet-0bfad12f6b
"""

awsabtch_output_0 = """
Scheduling:
  AwsBatchQueues:
    - CapacityType: ONDEMAND
      ComputeResources:
        - DesiredvCpus: 4
          InstanceTypes:
            - optimal
          MaxvCpus: 20
          MinvCpus: 0
          Name: batch-compute
          SpotBidPercentage: 85.0
      Networking:
        SubnetIds:
          - subnet-0bfad12f6b
      Name: batch-queue
  Scheduler: awsbatch
"""

awsabtch_input_1 = """
[cluster default]
vpc_settings = default
key_name = key1
scheduler = awsbatch
min_vcpus = 0
desired_vcpus = 4
max_vcpus = 20
spot_bid_percentage = 85
cluster_type = ondemand
compute_instance_type = t2.micro,optimal

[vpc default]
vpc_id = vpc-0e0f223cc35256b9a
master_subnet_id = subnet-0bfad12f6b586686c
vpc_security_group_id = sg-xxxxxx
additional_sg = sg-xxxxxx
compute_subnet_id = subnet-12345
"""

awsabtch_output_1 = """
Scheduling:
  AwsBatchQueues:
    - CapacityType: ONDEMAND
      ComputeResources:
        - DesiredvCpus: 4
          InstanceTypes:
            - t2.micro
            - optimal
          MaxvCpus: 20
          MinvCpus: 0
          Name: batch-compute
          SpotBidPercentage: 85.0
      Networking:
        AdditionalSecurityGroups:
          - sg-xxxxxx
        SecurityGroups:
          - sg-xxxxxx
        SubnetIds:
          - subnet-12345
      Name: batch-queue
  Scheduler: awsbatch
"""

awsabtch_input_2 = """
[cluster default]
vpc_settings = default
key_name = key1
scheduler = awsbatch
cluster_type = spot
compute_instance_type = t2.micro

[vpc default]
vpc_id = vpc-0e0f223cc35256b9a
master_subnet_id = subnet-0bfad12f6b586686c
compute_subnet_id = subnet-12345
"""

awsabtch_output_2 = """
Scheduling:
  AwsBatchQueues:
    - CapacityType: SPOT
      ComputeResources:
        - InstanceTypes:
            - t2.micro
          Name: batch-compute
      Networking:
        SubnetIds:
          - subnet-12345
      Name: batch-queue
  Scheduler: awsbatch
"""

sit_input_0 = """
[cluster default]
key_name = lab-3-your-key
vpc_settings = public
base_os = alinux2
scheduler = slurm
cluster_type = spot
s3_read_resource = arn:aws:s3:::testbucket/*
s3_read_write_resource = arn:aws:s3:::test/hello/*
pre_install = s3://testbucket/pre_install.sh
pre_install_args = 'R curl wget'
post_install = s3://testbucket/post_install.sh
post_install_args = "R curl wget"
spot_price = 2
max_queue_size = 5
disable_hyperthreading = false
initial_queue_size = 2
compute_instance_type = c5.xlarge
enable_efa = compute
enable_efa_gdr = compute
maintain_initial_size = false

[vpc public]
vpc_id = vpc-12345678
master_subnet_id = subnet-0bfad12f6b586686c
"""

sit_output_0 = """
Scheduling:
  Scheduler: slurm
  SlurmQueues:
    - CapacityType: SPOT
      ComputeResources:
        - DisableSimultaneousMultithreading: false
          Efa:
            Enabled: true
            GdrSupport: true
          InstanceType: c5.xlarge
          MaxCount: 5
          Name: default-resource
          SpotPrice: 2.0
      CustomActions:
        OnNodeConfigured:
          Args:
            - s3://testbucket/post_install.sh
            - R
            - curl
            - wget
          Script: s3://testbucket/post_install.sh
        OnNodeStart:
          Args:
            - s3://testbucket/pre_install.sh
            - R
            - curl
            - wget
          Script: s3://testbucket/pre_install.sh
      Iam:
        S3Access:
          - BucketName: testbucket
          - BucketName: test
            EnableWriteAccess: true
            KeyName: hello/*
      Name: default-queue
      Networking:
        SubnetIds:
          - subnet-0bfad12f6b586686c
"""
sit_input_1 = """
[cluster default]
key_name = lab-3-your-key
vpc_settings = public
base_os = alinux2
scheduler = slurm
cluster_type = ondemand
s3_read_resource = arn:aws:s3:::testbucket/*
s3_read_write_resource = arn:aws:s3:::test/hello/*
pre_install = s3://testbucket/pre_install.sh
pre_install_args = 'R curl wget'
post_install = s3://testbucket/post_install.sh
post_install_args = "R curl wget"
spot_price = 2
max_queue_size = 5
disable_hyperthreading = true
initial_queue_size = 2
maintain_initial_size = true
compute_instance_type = c5.xlarge

[vpc public]
vpc_id = vpc-12345678
master_subnet_id = subnet-0bfad12f6b586686c
"""

sit_output_1 = """
Scheduling:
  Scheduler: slurm
  SlurmQueues:
    - CapacityType: ONDEMAND
      ComputeResources:
        - DisableSimultaneousMultithreading: true
          InstanceType: c5.xlarge
          MaxCount: 5
          MinCount: 2
          Name: default-resource
          SpotPrice: 2.0
      CustomActions:
        OnNodeConfigured:
          Args:
            - s3://testbucket/post_install.sh
            - R
            - curl
            - wget
          Script: s3://testbucket/post_install.sh
        OnNodeStart:
          Args:
            - s3://testbucket/pre_install.sh
            - R
            - curl
            - wget
          Script: s3://testbucket/pre_install.sh
      Iam:
        S3Access:
          - BucketName: testbucket
          - BucketName: test
            EnableWriteAccess: true
            KeyName: hello/*
      Name: default-queue
      Networking:
        SubnetIds:
          - subnet-0bfad12f6b586686c
"""
scheduling_test = [
    (slurm_input_0, slurm_output_0, None),
    (slurm_input_1, slurm_output_1, None),
    (slurm_input_2, slurm_output_2, None),
    (awsabtch_input_0, awsabtch_output_0, None),
    (awsabtch_input_1, awsabtch_output_1, None),
    (awsabtch_input_2, awsabtch_output_2, None),
    (sit_input_0, sit_output_0, None),
    (sit_input_1, sit_output_1, None),
]
