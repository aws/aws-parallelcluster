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

import copy
from hashlib import sha1
from typing import Union

import pkg_resources
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as awslambda
from aws_cdk import core

from pcluster.constants import COOKBOOK_PACKAGES_VERSIONS, OS_MAPPING, PCLUSTER_STACK_PREFIX
from pcluster.models.cluster_config import (
    BaseClusterConfig,
    BaseComputeResource,
    BaseQueue,
    ClusterBucket,
    Ebs,
    HeadNode,
    SharedStorageType,
)
from pcluster.utils import get_installed_version


def get_block_device_mappings(node_config: Union[HeadNode, BaseQueue], os: str):
    """Return block device mapping."""
    block_device_mappings = []
    for _, (device_name_index, virtual_name_index) in enumerate(zip(list(map(chr, range(97, 121))), range(0, 24))):
        device_name = "/dev/xvdb{0}".format(device_name_index)
        virtual_name = "ephemeral{0}".format(virtual_name_index)
        block_device_mappings.append(
            ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(device_name=device_name, virtual_name=virtual_name)
        )

    # Root volume
    if node_config.storage and node_config.storage.root_volume:
        root_volume = copy.deepcopy(node_config.storage.root_volume)
    else:
        root_volume = Ebs()

    block_device_mappings.append(
        ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
            device_name=OS_MAPPING[os]["root-device"],
            ebs=ec2.CfnLaunchTemplate.EbsProperty(
                volume_size=root_volume.size,
                volume_type=root_volume.volume_type,
            ),
        )
    )
    return block_device_mappings


def create_hash_suffix(string_to_hash: str):
    """Create 16digit hash string."""
    return (
        string_to_hash
        if string_to_hash == "HeadNode"
        else sha1(string_to_hash.encode("utf-8")).hexdigest()[:16].capitalize()
    )


def get_user_data_content(user_data_path: str):
    """Retrieve user data content."""
    user_data_file_path = pkg_resources.resource_filename(__name__, user_data_path)
    with open(user_data_file_path, "r") as user_data_file:
        user_data_content = user_data_file.read()
    return user_data_content


def get_common_user_data_env(node: Union[HeadNode, BaseQueue], config: BaseClusterConfig) -> dict:
    """Return a dict containing the common env variables to be replaced in user data."""
    return {
        "YumProxy": node.networking.proxy if node.networking.proxy else "_none_",
        "DnfProxy": node.networking.proxy if node.networking.proxy else "",
        "AptProxy": node.networking.proxy if node.networking.proxy else "false",
        "ProxyServer": node.networking.proxy if node.networking.proxy else "NONE",
        "CustomChefCookbook": config.custom_chef_cookbook or "NONE",
        "ParallelClusterVersion": COOKBOOK_PACKAGES_VERSIONS["parallelcluster"],
        "CookbookVersion": COOKBOOK_PACKAGES_VERSIONS["cookbook"],
        "ChefVersion": COOKBOOK_PACKAGES_VERSIONS["chef"],
        "BerkshelfVersion": COOKBOOK_PACKAGES_VERSIONS["berkshelf"],
    }


def cluster_name(stack_name: str):
    """Return cluster name from stack name."""
    return stack_name.split(PCLUSTER_STACK_PREFIX)[1]


def get_shared_storage_ids_by_type(shared_storage_ids: dict, storage_type: SharedStorageType):
    """Return shared storage ids from the given list for the given type."""
    return ",".join(shared_storage_ids[storage_type]) if shared_storage_ids[storage_type] else "NONE"


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


def get_custom_tags(config: BaseClusterConfig):
    """Return a list of tags set by the user."""
    custom_tags = []
    if config.tags:
        custom_tags = [core.CfnTag(key=tag.key, value=tag.value) for tag in config.tags]
    return custom_tags


def get_default_instance_tags(
    stack_name: str,
    config: BaseClusterConfig,
    node: Union[HeadNode, BaseComputeResource],
    node_type: str,
    shared_storage_ids: dict,
):
    """Return a list of default tags to be used for instances."""
    return [
        core.CfnTag(key="Name", value=node_type),
        core.CfnTag(key="ClusterName", value=cluster_name(stack_name)),
        core.CfnTag(key="Application", value=stack_name),
        core.CfnTag(key="aws-parallelcluster-node-type", value=node_type),
        core.CfnTag(
            key="aws-parallelcluster-attributes",
            value="{BaseOS}, {Scheduler}, {Version}, {Architecture}".format(
                BaseOS=config.image.os,
                Scheduler=config.scheduling.scheduler,
                Version=get_installed_version(),
                Architecture=node.architecture,
            ),
        ),
        core.CfnTag(
            key="aws-parallelcluster-networking",
            value="EFA={0}".format("true" if node.efa and node.efa.enabled else "NONE"),
        ),
        core.CfnTag(
            key="aws-parallelcluster-filesystem",
            value="efs={efs}, multiebs={multiebs}, raid={raid}, fsx={fsx}".format(
                efs=len(shared_storage_ids[SharedStorageType.EFS]),
                multiebs=len(shared_storage_ids[SharedStorageType.EBS]),
                raid=len(shared_storage_ids[SharedStorageType.RAID]),
                fsx=len(shared_storage_ids[SharedStorageType.FSX]),
            ),
        ),
    ]


def get_default_volume_tags(stack_name: str, node_type: str):
    """Return a list of default tags to be used for volumes."""
    return [
        core.CfnTag(key="ClusterName", value=cluster_name(stack_name)),
        core.CfnTag(key="Application", value=stack_name),
        core.CfnTag(key="aws-parallelcluster-node-type", value=node_type),
    ]


def get_lambda_assume_role_policy_document():
    """Return default Lambda assume role policy document."""
    return iam.PolicyDocument(
        statements=[
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal(service="lambda.amazonaws.com")],
            )
        ]
    )


def get_cloud_watch_logs_policy_statement(resource: str):
    """Return CloudWatch Logs policy statement."""
    return iam.PolicyStatement(
        actions=["logs:CreateLogStream", "logs:PutLogEvents"],
        effect=iam.Effect.ALLOW,
        resources=[resource],
        sid="CloudWatchLogsPolicy",
    )


class PclusterLambdaConstruct(core.Construct):
    """Create a Lambda function with some pre-filled fields."""

    def __init__(
        self,
        scope: core.Construct,
        id: str,
        function_name: str,
        bucket: ClusterBucket,
        execution_role: iam.CfnRole,
        handler_func: str,
    ):
        super().__init__(scope, id)
        self.lambda_func = awslambda.CfnFunction(
            scope=scope,
            id=f"{function_name}Function",
            function_name=f"pcluster-{function_name}-{self._stack_unique_id()}",
            code=awslambda.CfnFunction.CodeProperty(
                s3_bucket=bucket.name,
                s3_key=f"{bucket.artifact_directory}/custom_resources_code/artifacts.zip",
            ),
            handler=f"{handler_func}.handler",
            memory_size=128,
            role=execution_role,
            runtime="python3.8",
            timeout=900,
        )

    def _stack_unique_id(self):
        return core.Fn.select(2, core.Fn.split("/", core.Stack.of(self).stack_id))

    def _format_arn(self, **kwargs):
        return core.Stack.of(self).format_arn(**kwargs)
