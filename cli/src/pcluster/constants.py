# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with
# the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

PCLUSTER_NAME_MAX_LENGTH = 60
PCLUSTER_NAME_REGEX = r"^([a-zA-Z][a-zA-Z0-9-]{0,%d})$"
PCLUSTER_ISSUES_LINK = "https://github.com/aws/aws-parallelcluster/issues"

CIDR_ALL_IPS = "0.0.0.0/0"

SUPPORTED_SCHEDULERS = ["slurm", "awsbatch"]
SCHEDULERS_SUPPORTING_IMDS_SECURED = ["slurm", "plugin"]
SUPPORTED_OSES = ["alinux2", "centos7", "ubuntu1804", "ubuntu2004"]
SUPPORTED_OSES_FOR_SCHEDULER = {"slurm": SUPPORTED_OSES, "plugin": SUPPORTED_OSES, "awsbatch": ["alinux2"]}
DELETION_POLICIES = ["Retain", "Delete"]
DELETION_POLICIES_WITH_SNAPSHOT = DELETION_POLICIES + ["Snapshot"]
SUPPORTED_ARCHITECTURES = ["x86_64", "arm64"]
SUPPORTED_OSES_FOR_ARCHITECTURE = {"x86_64": SUPPORTED_OSES, "arm64": SUPPORTED_OSES}

OS_MAPPING = {
    "centos7": {"user": "centos", "root-device": "/dev/sda1"},
    "alinux2": {"user": "ec2-user", "root-device": "/dev/xvda"},
    "ubuntu1804": {"user": "ubuntu", "root-device": "/dev/sda1"},
    "ubuntu2004": {"user": "ubuntu", "root-device": "/dev/sda1"},
}

OS_TO_IMAGE_NAME_PART_MAP = {
    "alinux2": "amzn2-hvm",
    "centos7": "centos7-hvm",
    "ubuntu1804": "ubuntu-1804-lts-hvm",
    "ubuntu2004": "ubuntu-2004-lts-hvm",
}

IMAGE_NAME_PART_TO_OS_MAP = {value: key for key, value in OS_TO_IMAGE_NAME_PART_MAP.items()}

# Describe the list of requirements to be satisfied by the Pcluster AWS Batch CLI to manage the cluster.
# It must be in the form <package-name><comparison-operator><version>
# It can contain multiple items separated by a colon.
# i.e. aws-parallelcluster-awsbatch-cli>=2.0.0,aws-parallelcluster-awsbatch-cli<3.0.0
AWSBATCH_CLI_REQUIREMENTS = "aws-parallelcluster-awsbatch-cli<2.0.0"

FSX_SSD_THROUGHPUT = [50, 100, 200]
FSX_HDD_THROUGHPUT = [12, 40]

EBS_VOLUME_TYPE_IOPS_DEFAULT = {
    "io1": 100,
    "io2": 100,
    "gp3": 3000,
}
EBS_VOLUME_SIZE_DEFAULT = 35
EBS_VOLUME_TYPE_DEFAULT = "gp2"

DEFAULT_MAX_COUNT = 10
DEFAULT_MIN_COUNT = 0
MAX_NUMBER_OF_QUEUES = 10
MAX_NUMBER_OF_COMPUTE_RESOURCES = 5

MAX_STORAGE_COUNT = {"ebs": 5, "efs": 1, "fsx": 1, "raid": 1}

COOKBOOK_PACKAGES_VERSIONS = {
    "parallelcluster": "3.2.0b1",
    "cookbook": "aws-parallelcluster-cookbook-3.2.0b1",
    "chef": "17.2.29",
    "berkshelf": "7.2.0",
    "ami": "dev",
}

CW_DASHBOARD_ENABLED_DEFAULT = True
CW_LOGS_ENABLED_DEFAULT = True
CW_LOGS_RETENTION_DAYS_DEFAULT = 14
CW_LOGS_CFN_PARAM_NAME = "ClusterCWLogGroup"
CW_LOG_GROUP_NAME_PREFIX = "/aws/parallelcluster/"

STACK_EVENTS_LOG_STREAM_NAME_FORMAT = "{}-cfn-events"

PCLUSTER_IMAGE_NAME_REGEX = r"^[-_A-Za-z0-9{][-_A-Za-z0-9\s:{}\.]+[-_A-Za-z0-9}]$"
PCLUSTER_IMAGE_ID_REGEX = r"^([a-zA-Z][a-zA-Z0-9-]{0,127})$"

PCLUSTER_SLURM_DYNAMODB_PREFIX = "parallelcluster-slurm-"
PCLUSTER_DYNAMODB_PREFIX = "parallelcluster-"
PCLUSTER_PREFIX = "parallelcluster:"
PCLUSTER_IMAGE_NAME_TAG = f"{PCLUSTER_PREFIX}image_name"
PCLUSTER_IMAGE_ID_TAG = f"{PCLUSTER_PREFIX}image_id"
PCLUSTER_IMAGE_BUILD_STATUS_TAG = f"{PCLUSTER_PREFIX}build_status"
PCLUSTER_IMAGE_CONFIG_TAG = f"{PCLUSTER_PREFIX}build_config"
PCLUSTER_S3_IMAGE_DIR_TAG = f"{PCLUSTER_PREFIX}s3_image_dir"
PCLUSTER_S3_CLUSTER_DIR_TAG = f"{PCLUSTER_PREFIX}cluster_dir"
PCLUSTER_S3_BUCKET_TAG = f"{PCLUSTER_PREFIX}s3_bucket"
PCLUSTER_IMAGE_OS_TAG = f"{PCLUSTER_PREFIX}os"
PCLUSTER_IMAGE_BUILD_LOG_TAG = f"{PCLUSTER_PREFIX}build_log"
PCLUSTER_VERSION_TAG = f"{PCLUSTER_PREFIX}version"
# PCLUSTER_CLUSTER_NAME_TAG needs to be the same as the hard coded strings in node package
# and in cleanup_resource.py used by Lambda function
PCLUSTER_CLUSTER_NAME_TAG = f"{PCLUSTER_PREFIX}cluster-name"
# PCLUSTER_NODE_TYPE_TAG needs to be the same as the hard coded strings in node package
PCLUSTER_NODE_TYPE_TAG = f"{PCLUSTER_PREFIX}node-type"
PCLUSTER_QUEUE_NAME_TAG = f"{PCLUSTER_PREFIX}queue-name"
PCLUSTER_COMPUTE_RESOURCE_NAME_TAG = f"{PCLUSTER_PREFIX}compute-resource-name"
IMAGEBUILDER_ARN_TAG = "Ec2ImageBuilderArn"
PCLUSTER_S3_ARTIFACTS_DICT = {
    "root_directory": "parallelcluster",
    "root_cluster_directory": "clusters",
    "source_config_name": "cluster-config.yaml",
    "image_config_name": "image-config.yaml",
    "config_name": "cluster-config-with-implied-values.yaml",
    "template_name": "aws-parallelcluster.cfn.yaml",
    "scheduler_plugin_template_name": "scheduler-plugin-substack.cfn",
    "instance_types_data_name": "instance-types-data.json",
    "custom_artifacts_name": "artifacts.zip",
    "scheduler_resources_name": "scheduler_resources.zip",
}

PCLUSTER_TAG_VALUE_REGEX = r"^([\w\+\-\=\.\_\:\@/]{0,256})$"

IMAGEBUILDER_RESOURCE_NAME_PREFIX = "ParallelClusterImage"

IAM_ROLE_PATH = "/parallelcluster/"

PCLUSTER_S3_BUCKET_VERSION = "v1"

SUPPORTED_REGIONS = [
    "af-south-1",
    "ap-east-1",
    "ap-northeast-1",
    "ap-northeast-2",
    "ap-south-1",
    "ap-southeast-1",
    "ap-southeast-2",
    "ca-central-1",
    "cn-north-1",
    "cn-northwest-1",
    "eu-central-1",
    "eu-north-1",
    "eu-south-1",
    "eu-west-1",
    "eu-west-2",
    "eu-west-3",
    "me-south-1",
    "sa-east-1",
    "us-east-1",
    "us-east-2",
    "us-gov-east-1",
    "us-gov-west-1",
    "us-west-1",
    "us-west-2",
]

SCHEDULER_PLUGIN_MAX_NUMBER_OF_USERS = 10
