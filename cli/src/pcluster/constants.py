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
from enum import Enum

PCLUSTER_NAME_MAX_LENGTH = 60
# When Slurm accounting is enabled, Slurm creates database tables with the format 'cluster_name' + 'suffix'.
# MySQL and MariaDB have a maximum table name length of 64 characters.
# The longest suffix used by Slurm is 24 chars, therefore the cluster name must be at most 40 chars long.
PCLUSTER_NAME_MAX_LENGTH_SLURM_ACCOUNTING = 40
PCLUSTER_NAME_REGEX = r"^([a-zA-Z][a-zA-Z0-9-]{0,%d})$"
PCLUSTER_ISSUES_LINK = "https://github.com/aws/aws-parallelcluster/issues"
PCLUSTER_AMI_ID_REGEX = r"^ami-[0-9a-z]{8}$|^ami-[0-9a-z]{17}$"

CIDR_ALL_IPS = "0.0.0.0/0"

SUPPORTED_SCHEDULERS = ["slurm", "awsbatch"]
SCHEDULERS_SUPPORTING_IMDS_SECURED = ["slurm"]
SUPPORTED_OSES = ["alinux2", "centos7", "ubuntu2004", "ubuntu2204", "rhel8"]
SUPPORTED_OSES_FOR_SCHEDULER = {"slurm": SUPPORTED_OSES, "awsbatch": ["alinux2"]}
DELETE_POLICY = "Delete"
RETAIN_POLICY = "Retain"
DELETION_POLICIES = [DELETE_POLICY, RETAIN_POLICY]
DELETION_POLICIES_WITH_SNAPSHOT = DELETION_POLICIES + ["Snapshot"]
SUPPORTED_ARCHITECTURES = ["x86_64", "arm64"]
SUPPORTED_OSES_FOR_ARCHITECTURE = {"x86_64": SUPPORTED_OSES, "arm64": SUPPORTED_OSES}
SLURM = "slurm"
AWSBATCH = "awsbatch"

OS_MAPPING = {
    "centos7": {"user": "centos"},
    "alinux2": {"user": "ec2-user"},
    "ubuntu2004": {"user": "ubuntu"},
    "ubuntu2204": {"user": "ubuntu"},
    "rhel8": {"user": "ec2-user"},
}

OS_TO_IMAGE_NAME_PART_MAP = {
    "alinux2": "amzn2-hvm",
    "centos7": "centos7-hvm",
    "ubuntu2004": "ubuntu-2004-lts-hvm",
    "ubuntu2204": "ubuntu-2204-lts-hvm",
    "rhel8": "rhel8-hvm",
}

IMAGE_NAME_PART_TO_OS_MAP = {value: key for key, value in OS_TO_IMAGE_NAME_PART_MAP.items()}

# Describe the list of requirements to be satisfied by the Pcluster AWS Batch CLI to manage the cluster.
# It must be in the form <package-name><comparison-operator><version>
# It can contain multiple items separated by a colon.
# i.e. aws-parallelcluster-awsbatch-cli>=2.0.0,aws-parallelcluster-awsbatch-cli<3.0.0
AWSBATCH_CLI_REQUIREMENTS = "aws-parallelcluster-awsbatch-cli<2.0.0"


FSX_SSD_THROUGHPUT = {"PERSISTENT_1": [50, 100, 200], "PERSISTENT_2": [125, 250, 500, 1000]}
FSX_HDD_THROUGHPUT = [12, 40]

LUSTRE = "LUSTRE"
OPENZFS = "OPENZFS"
ONTAP = "ONTAP"
FILECACHE = "FILECACHE"

FSX_LUSTRE = "FsxLustre"
FSX_OPENZFS = "FsxOpenZfs"
FSX_ONTAP = "FsxOntap"
FSX_FILE_CACHE = "FsxFileCache"

# https://docs.aws.amazon.com/fsx/latest/APIReference/API_DescribeVolumes.html#FSx-DescribeVolumes-request-VolumeIds.
FSX_VOLUME_ID_REGEX = r"^fsvol-[0-9a-f]{17}$"
# https://docs.aws.amazon.com/fsx/latest/APIReference/API_FileCacheCreating.html#FSx-Type-FileCacheCreating-FileCacheId:~:text=Pattern%3A-,%5E(fc%2D%5B0%2D9a%2Df%5D%7B8%2C%7D)%24,-Required%3A%20No
FSX_FILE_CACHE_ID_REGEX = r"^(fc-[0-9a-f]{8,18})$"

FSX_PORTS = {
    # Lustre Security group: https://docs.aws.amazon.com/fsx/latest/LustreGuide/limit-access-security-groups.html
    LUSTRE: {"tcp": [988]},
    # OpenZFS Security group: https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/limit-access-security-groups.html
    OPENZFS: {"tcp": [111, 2049, 20001, 20002, 20003], "udp": [111, 2049, 20001, 20002, 20003]},
    # Ontap Security group: https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/limit-access-security-groups.html
    ONTAP: {"tcp": [111, 635, 2049, 4046], "udp": [111, 635, 2049, 4046]},
}

ALL_PORTS_RANGE = (0, 65535)
SLURM_PORTS_RANGE = (6819, 6829)
NFS_PORT = 2049
EFS_PORT = 2049

EBS_VOLUME_TYPE_IOPS_DEFAULT = {
    "io1": 100,
    "io2": 100,
    "gp3": 3000,
}
EBS_VOLUME_SIZE_DEFAULT = 35
EBS_VOLUME_TYPE_DEFAULT = "gp3"
EBS_VOLUME_TYPE_DEFAULT_US_ISO = "gp2"

DEFAULT_MAX_COUNT = 10
DEFAULT_MIN_COUNT = 0
MAX_NUMBER_OF_QUEUES = 50
# Allow for flexibility in how compute resources are distributed in the cluster
MAX_NUMBER_OF_COMPUTE_RESOURCES_PER_CLUSTER = MAX_COMPUTE_RESOURCES_PER_QUEUE = 50
MIN_SLURM_NODE_PRIORITY = 1
MAX_SLURM_NODE_PRIORITY = 2**32 - 1  # max value of uint32_t

# Thresholds used to trigger a warning if Memory Based Scheduling and Flexible Instance Types are used together
MIN_MEMORY_ABSOLUTE_DIFFERENCE = 4096
MIN_MEMORY_PRECENTAGE_DIFFERENCE = 0.20

MAX_EBS_COUNT = 5
MAX_NEW_STORAGE_COUNT = {"efs": 1, "fsx": 1, "raid": 1}
MAX_EXISTING_STORAGE_COUNT = {"efs": 20, "fsx": 20, "raid": 0}

COOKBOOK_PACKAGES_VERSIONS = {
    "parallelcluster": "3.7.0b1",
    "cookbook": "aws-parallelcluster-cookbook-3.7.0b1",
    "chef": "17.2.29",
    "berkshelf": "7.2.0",
    "ami": "dev",
}

CW_DASHBOARD_ENABLED_DEFAULT = True
CW_LOGS_ENABLED_DEFAULT = True
CW_LOGS_ROTATION_ENABLED_DEFAULT = True
CW_LOGS_RETENTION_DAYS_DEFAULT = 180
CW_LOGS_CFN_PARAM_NAME = "ClusterCWLogGroup"
CW_LOG_GROUP_NAME_PREFIX = "/aws/parallelcluster/"
CW_ALARM_PERIOD_DEFAULT = 60
CW_ALARM_PERCENT_THRESHOLD_DEFAULT = 90
CW_ALARM_EVALUATION_PERIODS_DEFAULT = 1
CW_ALARM_DATAPOINTS_TO_ALARM_DEFAULT = 1
DETAILED_MONITORING_ENABLED_DEFAULT = False

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
PCLUSTER_LOGIN_NODES_POOL_NAME_TAG = f"{PCLUSTER_PREFIX}login-nodes-pool-name"
IMAGEBUILDER_ARN_TAG = "Ec2ImageBuilderArn"
PCLUSTER_S3_ARTIFACTS_DICT = {
    "root_directory": "parallelcluster",
    "root_cluster_directory": "clusters",
    "source_config_name": "cluster-config.yaml",
    "image_config_name": "image-config.yaml",
    "config_name": "cluster-config-with-implied-values.yaml",
    "template_name": "aws-parallelcluster.cfn.yaml",
    "instance_types_data_name": "instance-types-data.json",
    "custom_artifacts_name": "artifacts.zip",
    "scheduler_resources_name": "scheduler_resources.zip",
    "change_set_name": "change-set.json",
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
    "us-iso-east-1",
    "us-isob-east-1",
    "us-gov-east-1",
    "us-gov-west-1",
    "us-west-1",
    "us-west-2",
]

# see https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html
NODEJS_MIN_VERSION = "10.13.0"
NODEJS_INCOMPATIBLE_VERSION_RANGE = ["13.0.0", "13.6.0"]

NODE_BOOTSTRAP_TIMEOUT = 1800

# DirectoryService
DIRECTORY_SERVICE_RESERVED_SETTINGS = {"id_provider": "ldap"}

DEFAULT_EPHEMERAL_DIR = "/scratch"

LAMBDA_VPC_ACCESS_MANAGED_POLICY = "arn:${AWS::Partition}:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"

IAM_NAME_PREFIX_LENGTH_LIMIT = 30
IAM_PATH_LENGTH_LIMIT = 512


# Features support
# By default, all features are considered supported.
# To mark a feature as unsupported for certain regions,
# add the entry to the map below by region prefixes.
class Feature(Enum):
    """
    Enumeration of features.

    We do not expect this enumeration to list all the features,
    but at least those that are considered for feature flagging.
    """

    BATCH = "AWS Batch scheduler"
    DCV = "NICE DCV"
    FSX_LUSTRE = "FSx Lustre"
    FSX_FILE_CACHE = "FSx FileCache"
    FSX_ONTAP = "FSx ONTAP"
    FSX_OPENZFS = "FSx OpenZfs"
    SLURM_DATABASE = "SLURM Database"
    CLUSTER_HEALTH_METRICS = "Cluster Health Metrics"


UNSUPPORTED_FEATURES_MAP = {
    Feature.BATCH: ["ap-northeast-3", "us-iso"],
    Feature.DCV: ["us-iso"],
    Feature.FSX_LUSTRE: ["us-iso"],
    Feature.FSX_FILE_CACHE: ["us-iso"],
    Feature.FSX_ONTAP: ["us-iso"],
    Feature.FSX_OPENZFS: ["us-iso"],
    Feature.SLURM_DATABASE: [],
    Feature.CLUSTER_HEALTH_METRICS: ["us-iso"],
}


# Operations support
# By default, all operations are considered supported.
# To mark an operation as unsupported for certain regions,
# add the entry to the map below by region prefixes.
class Operation(Enum):
    """
    Enumeration of operations.

    We do not expect this enumeration to list all the operations,
    but at least those that are considered for operations flagging.
    """

    BUILD_IMAGE = "build-image"
    CONFIGURE = "configure"
    CREATE_CLUSTER = "create-cluster"
    DCV_CONNECT = "dcv-connect"
    DELETE_CLUSTER = "delete-cluster"
    DELETE_CLUSTER_INSTANCES = "delete-cluster-instances"
    DELETE_IMAGE = "delete-image"
    DESCRIBE_CLUSTER = "describe-cluster"
    DESCRIBE_CLUSTER_INSTANCES = "describe-cluster-instances"
    DESCRIBE_COMPUTE_FLEET = "describe-compute-fleet"
    DESCRIBE_IMAGE = "describe-image"
    EXPORT_CLUSTER_LOGS = "export-cluster-logs"
    EXPORT_IMAGE_LOGS = "export-image-logs"
    GET_CLUSTER_LOG_EVENTS = "get-cluster-log-events"
    GET_CLUSTER_STACK_EVENTS = "get-cluster-stack-events"
    GET_IMAGE_LOG_EVENTS = "get-image-log-events"
    GET_IMAGE_STACK_EVENTS = "get-image-stack-events"
    LIST_CLUSTER_LOG_STREAMS = "list-cluster-log-streams"
    LIST_CLUSTERS = "list-clusters"
    LIST_IMAGES = "list-images"
    LIST_IMAGE_LOG_STREAMS = "list-image-log-streams"
    LIST_OFFICIAL_IMAGES = "list-official-images"
    SSH = "ssh"
    UPDATE_CLUSTER = "update-cluster"
    UPDATE_COMOPUTE_FLEET = "update-compute-fleet"
    VERSION = "version"


UNSUPPORTED_OPERATIONS_MAP = {
    Operation.BUILD_IMAGE: ["us-iso"],
    Operation.DELETE_IMAGE: ["us-iso"],
    Operation.DESCRIBE_IMAGE: ["us-iso"],
    Operation.LIST_IMAGES: ["us-iso"],
    Operation.EXPORT_IMAGE_LOGS: ["us-iso"],
    Operation.GET_IMAGE_LOG_EVENTS: ["us-iso"],
    Operation.GET_IMAGE_STACK_EVENTS: ["us-iso"],
    Operation.LIST_IMAGE_LOG_STREAMS: ["us-iso"],
}

MAX_TAGS_COUNT = 40  # Tags are limited to 50, reserve some tags for parallelcluster specified tags

IAM_ROLE_REGEX = "^arn:.*:role/"
IAM_INSTANCE_PROFILE_REGEX = "^arn:.*:instance-profile/"
IAM_POLICY_REGEX = "^arn:.*:policy/"
