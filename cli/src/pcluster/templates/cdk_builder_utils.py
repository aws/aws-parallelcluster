# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

from hashlib import sha1
from typing import List, Union

import pkg_resources
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as awslambda
from aws_cdk import aws_logs as logs
from aws_cdk.aws_iam import ManagedPolicy, PermissionsBoundary
from aws_cdk.core import CfnDeletionPolicy, CfnTag, Construct, Fn, Stack

from pcluster.config.cluster_config import (
    BaseClusterConfig,
    BaseComputeResource,
    BaseQueue,
    HeadNode,
    LocalStorage,
    RootVolume,
    SharedStorageType,
)
from pcluster.constants import (
    COOKBOOK_PACKAGES_VERSIONS,
    CW_LOGS_RETENTION_DAYS_DEFAULT,
    IAM_ROLE_PATH,
    OS_MAPPING,
    PCLUSTER_CLUSTER_NAME_TAG,
    PCLUSTER_NODE_TYPE_TAG,
)
from pcluster.models.s3_bucket import S3Bucket
from pcluster.utils import get_installed_version


def get_block_device_mappings(local_storage: LocalStorage, os: str):
    """Return block device mapping."""
    block_device_mappings = []
    for _, (device_name_index, virtual_name_index) in enumerate(zip(list(map(chr, range(97, 121))), range(0, 24))):
        device_name = "/dev/xvdb{0}".format(device_name_index)
        virtual_name = "ephemeral{0}".format(virtual_name_index)
        block_device_mappings.append(
            ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(device_name=device_name, virtual_name=virtual_name)
        )

    root_volume = local_storage.root_volume or RootVolume()

    block_device_mappings.append(
        ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
            device_name=OS_MAPPING[os]["root-device"],
            ebs=ec2.CfnLaunchTemplate.EbsProperty(
                volume_size=root_volume.size,
                encrypted=root_volume.encrypted,
                volume_type=root_volume.volume_type,
                iops=root_volume.iops,
                throughput=root_volume.throughput,
                delete_on_termination=root_volume.delete_on_termination,
            ),
        )
    )
    return block_device_mappings


def create_hash_suffix(string_to_hash: str):
    """Create 16digit hash string."""
    return (
        string_to_hash
        if string_to_hash == "HeadNode"
        else sha1(string_to_hash.encode("utf-8")).hexdigest()[:16].capitalize()  # nosec nosemgrep
    )


def get_user_data_content(user_data_path: str):
    """Retrieve user data content."""
    user_data_file_path = pkg_resources.resource_filename(__name__, user_data_path)
    with open(user_data_file_path, "r", encoding="utf-8") as user_data_file:
        user_data_content = user_data_file.read()
    return user_data_content


def get_common_user_data_env(node: Union[HeadNode, BaseQueue], config: BaseClusterConfig) -> dict:
    """Return a dict containing the common env variables to be replaced in user data."""
    return {
        "YumProxy": node.networking.proxy.http_proxy_address if node.networking.proxy else "_none_",
        "DnfProxy": node.networking.proxy.http_proxy_address if node.networking.proxy else "",
        "AptProxy": node.networking.proxy.http_proxy_address if node.networking.proxy else "false",
        "ProxyServer": node.networking.proxy.http_proxy_address if node.networking.proxy else "NONE",
        "CustomChefCookbook": config.custom_chef_cookbook or "NONE",
        "ParallelClusterVersion": COOKBOOK_PACKAGES_VERSIONS["parallelcluster"],
        "CookbookVersion": COOKBOOK_PACKAGES_VERSIONS["cookbook"],
        "ChefVersion": COOKBOOK_PACKAGES_VERSIONS["chef"],
        "BerkshelfVersion": COOKBOOK_PACKAGES_VERSIONS["berkshelf"],
    }


def get_shared_storage_ids_by_type(shared_storage_ids: dict, storage_type: SharedStorageType):
    """Return shared storage ids from the given list for the given type."""
    return (
        ",".join(storage_mapping.id for storage_mapping in shared_storage_ids[storage_type])
        if shared_storage_ids[storage_type]
        else "NONE"
    )


def get_shared_storage_options_by_type(shared_storage_options: dict, storage_type: SharedStorageType):
    """Return shared storage options from the given list for the given type."""
    default_storage_options = {
        SharedStorageType.EBS: "NONE,NONE,NONE,NONE,NONE",
        SharedStorageType.RAID: "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
        SharedStorageType.EFS: "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
        SharedStorageType.FSX: ("NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE"),
    }
    return (
        shared_storage_options[storage_type]
        if shared_storage_options[storage_type]
        else default_storage_options[storage_type]
    )


def get_mount_dirs_by_type(shared_storage_options: dict, storage_type: SharedStorageType):
    """Return mount dirs retrieved from shared storage, formatted as comma separated list."""
    storage_options = shared_storage_options.get(storage_type)
    if not storage_options:
        return "NONE"
    if storage_type == SharedStorageType.EBS:
        # The whole options for EBS represent the mount dirs.
        return storage_options
    option_list = storage_options.split(",")
    return option_list[0]


def get_custom_tags(config: BaseClusterConfig, raw_dict: bool = False):
    """Return a list of tags set by the user."""
    if raw_dict:
        custom_tags = {tag.key: tag.value for tag in config.tags} if config.tags else {}
    else:
        custom_tags = [CfnTag(key=tag.key, value=tag.value) for tag in config.tags] if config.tags else []
    return custom_tags


def get_default_instance_tags(
    stack_name: str,
    config: BaseClusterConfig,
    node: Union[HeadNode, BaseComputeResource],
    node_type: str,
    shared_storage_ids: dict,
    raw_dict: bool = False,
):
    """Return a list of default tags to be used for instances."""
    tags = {
        "Name": node_type,
        PCLUSTER_CLUSTER_NAME_TAG: stack_name,
        PCLUSTER_NODE_TYPE_TAG: node_type,
        "parallelcluster:attributes": "{BaseOS}, {Scheduler}, {Version}, {Architecture}".format(
            BaseOS=config.image.os,
            Scheduler=config.scheduling.scheduler,
            Version=get_installed_version(),
            Architecture=node.architecture if hasattr(node, "architecture") else "NONE",
        ),
        "parallelcluster:networking": "EFA={0}".format(
            "true" if hasattr(node, "efa") and node.efa and node.efa.enabled else "NONE"
        ),
        "parallelcluster:filesystem": "efs={efs}, multiebs={multiebs}, raid={raid}, fsx={fsx}".format(
            efs=len(shared_storage_ids[SharedStorageType.EFS]),
            multiebs=len(shared_storage_ids[SharedStorageType.EBS]),
            raid=len(shared_storage_ids[SharedStorageType.RAID]),
            fsx=len(shared_storage_ids[SharedStorageType.FSX]),
        ),
    }
    if config.is_intel_hpc_platform_enabled:
        tags["parallelcluster:intel-hpc"] = "enable_intel_hpc_platform=true"
    return tags if raw_dict else [CfnTag(key=key, value=value) for key, value in tags.items()]


def get_default_volume_tags(stack_name: str, node_type: str, raw_dict: bool = False):
    """Return a list of default tags to be used for volumes."""
    tags = {
        PCLUSTER_CLUSTER_NAME_TAG: stack_name,
        PCLUSTER_NODE_TYPE_TAG: node_type,
    }
    return tags if raw_dict else [CfnTag(key=key, value=value) for key, value in tags.items()]


def get_assume_role_policy_document(service: str):
    """Return default service assume role policy document."""
    return iam.PolicyDocument(
        statements=[
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal(service=service)],
            )
        ]
    )


def get_cloud_watch_logs_policy_statement(resource: str) -> iam.PolicyStatement:
    """Return CloudWatch Logs policy statement."""
    return iam.PolicyStatement(
        actions=["logs:CreateLogStream", "logs:PutLogEvents"],
        effect=iam.Effect.ALLOW,
        resources=[resource],
        sid="CloudWatchLogsPolicy",
    )


def get_cloud_watch_logs_retention_days(config: BaseClusterConfig) -> int:
    """Return value to use for CloudWatch logs retention days."""
    return (
        config.monitoring.logs.cloud_watch.retention_in_days
        if config.is_cw_logging_enabled
        else CW_LOGS_RETENTION_DAYS_DEFAULT
    )


def get_log_group_deletion_policy(config: BaseClusterConfig):
    return convert_deletion_policy(config.monitoring.logs.cloud_watch.deletion_policy)


def convert_deletion_policy(deletion_policy: str):
    if deletion_policy == "Retain":
        return CfnDeletionPolicy.RETAIN
    elif deletion_policy == "Delete":
        return CfnDeletionPolicy.DELETE
    elif deletion_policy == "Snapshot":
        return CfnDeletionPolicy.SNAPSHOT
    return None


def get_queue_security_groups_full(compute_security_groups: dict, queue: BaseQueue):
    """Return full security groups to be used for the queue, default plus additional ones."""
    queue_security_groups = []

    # Default security groups, created by us or provided by the user
    if compute_security_groups and compute_security_groups.get(queue.name, None):
        queue_security_groups.append(compute_security_groups[queue.name].ref)
    elif queue.networking.security_groups:
        queue_security_groups.extend(queue.networking.security_groups)

    # Additional security groups
    if queue.networking.additional_security_groups:
        queue_security_groups.extend(queue.networking.additional_security_groups)

    return queue_security_groups


def add_lambda_cfn_role(scope, function_id: str, statements: List[iam.PolicyStatement]):
    """Return a CfnRole to be used for a Lambda function."""
    return iam.CfnRole(
        scope,
        f"{function_id}FunctionExecutionRole",
        path=IAM_ROLE_PATH,
        assume_role_policy_document=get_assume_role_policy_document("lambda.amazonaws.com"),
        policies=[
            iam.CfnRole.PolicyProperty(
                policy_document=iam.PolicyDocument(statements=statements),
                policy_name="LambdaPolicy",
            ),
        ],
    )


def apply_permissions_boundary(boundary, scope):
    """Apply a permissions boundary to all IAM roles defined in the scope."""
    if boundary:
        boundary = ManagedPolicy.from_managed_policy_arn(scope, "Boundary", boundary)
        PermissionsBoundary.of(scope).apply(boundary)


class PclusterLambdaConstruct(Construct):
    """Create a Lambda function with some pre-filled fields."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        function_id: str,
        bucket: S3Bucket,
        config: BaseClusterConfig,
        execution_role: iam.CfnRole,
        handler_func: str,
        timeout: int = 900,
    ):
        super().__init__(scope, id)

        function_name = f"pcluster-{function_id}-{self._stack_unique_id()}"

        self.log_group = logs.CfnLogGroup(
            scope,
            f"{function_id}FunctionLogGroup",
            log_group_name=f"/aws/lambda/{function_name}",
            retention_in_days=get_cloud_watch_logs_retention_days(config),
        )
        self.log_group.cfn_options.deletion_policy = get_log_group_deletion_policy(config)

        self.lambda_func = awslambda.CfnFunction(
            scope,
            f"{function_id}Function",
            function_name=function_name,
            code=awslambda.CfnFunction.CodeProperty(
                s3_bucket=bucket.name,
                s3_key=f"{bucket.artifact_directory}/custom_resources/artifacts.zip",
            ),
            handler=f"{handler_func}.handler",
            memory_size=128,
            role=execution_role,
            runtime="python3.8",
            timeout=timeout,
        )

    def _stack_unique_id(self):
        return Fn.select(2, Fn.split("/", Stack.of(self).stack_id))

    def _format_arn(self, **kwargs):
        return Stack.of(self).format_arn(**kwargs)
