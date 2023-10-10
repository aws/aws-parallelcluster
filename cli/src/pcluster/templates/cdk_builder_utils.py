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

# pylint: disable=too-many-lines
import abc
from hashlib import sha1, sha256
from typing import List, Union

import pkg_resources
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as awslambda
from aws_cdk import aws_logs as logs
from aws_cdk.aws_iam import ManagedPolicy, PermissionsBoundary
from aws_cdk.core import Arn, ArnFormat, CfnDeletionPolicy, CfnTag, Construct, Fn, Stack

from pcluster.config.cluster_config import (
    BaseClusterConfig,
    BaseComputeResource,
    BaseQueue,
    HeadNode,
    LoginNodesPool,
    SharedStorageType,
    SlurmClusterConfig,
    SlurmComputeResource,
    SlurmQueue,
)
from pcluster.constants import (
    COOKBOOK_PACKAGES_VERSIONS,
    CW_LOGS_RETENTION_DAYS_DEFAULT,
    IAM_ROLE_PATH,
    LAMBDA_VPC_ACCESS_MANAGED_POLICY,
    PCLUSTER_CLUSTER_NAME_TAG,
    PCLUSTER_DYNAMODB_PREFIX,
    PCLUSTER_NODE_TYPE_TAG,
)
from pcluster.launch_template_utils import _LaunchTemplateBuilder
from pcluster.models.s3_bucket import S3Bucket, parse_bucket_url
from pcluster.utils import (
    get_installed_version,
    get_resource_name_from_resource_arn,
    policy_name_to_arn,
    split_resource_prefix,
)

PCLUSTER_LAMBDA_PREFIX = "pcluster-"


def create_hash_suffix(string_to_hash: str):
    """Create 16digit hash string."""
    return (
        string_to_hash
        if string_to_hash == "HeadNode"
        # A nosec comment is appended to the following line in order to disable the B324 check.
        # The sha1 is used just as a hashing function.
        # [B324:hashlib] Use of weak MD4, MD5, or SHA1 hash for security. Consider usedforsecurity=False
        else sha1(string_to_hash.encode("utf-8")).hexdigest()[:16].capitalize()  # nosec nosemgrep
    )


def get_user_data_content(user_data_path: str):
    """Retrieve user data content."""
    user_data_file_path = pkg_resources.resource_filename(__name__, user_data_path)
    with open(user_data_file_path, "r", encoding="utf-8") as user_data_file:
        user_data_content = user_data_file.read()
    return user_data_content


def get_common_user_data_env(node: Union[HeadNode, SlurmQueue, LoginNodesPool], config: BaseClusterConfig) -> dict:
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


def get_slurm_specific_dna_json_for_head_node(config: SlurmClusterConfig, scheduler_resources) -> dict:
    """Return a dict containing slurm specific settings to be written to dna.json of head node."""
    return {
        "dns_domain": scheduler_resources.cluster_hosted_zone.name if scheduler_resources.cluster_hosted_zone else "",
        "hosted_zone": scheduler_resources.cluster_hosted_zone.ref if scheduler_resources.cluster_hosted_zone else "",
        "slurm_ddb_table": scheduler_resources.dynamodb_table.ref,
        "use_private_hostname": str(config.scheduling.settings.dns.use_ec2_hostnames).lower(),
    }


def get_directory_service_dna_json_for_head_node(config: BaseClusterConfig) -> dict:
    """Return a dict containing directory service settings to be written to dna.json of head node."""
    directory_service = config.directory_service
    return (
        {
            "directory_service": {
                "enabled": "true",
                "domain_name": directory_service.domain_name,
                "domain_addr": directory_service.domain_addr,
                "password_secret_arn": directory_service.password_secret_arn,
                "domain_read_only_user": directory_service.domain_read_only_user,
                "ldap_tls_ca_cert": directory_service.ldap_tls_ca_cert or "NONE",
                "ldap_tls_req_cert": directory_service.ldap_tls_req_cert or "NONE",
                "ldap_access_filter": directory_service.ldap_access_filter or "NONE",
                "generate_ssh_keys_for_users": str(directory_service.generate_ssh_keys_for_users).lower(),
                "additional_sssd_configs": directory_service.additional_sssd_configs,
            }
        }
        if directory_service
        else {}
    )


def to_comma_separated_string(list, use_lower_case=False):
    result = ",".join(str(item) for item in list)
    if use_lower_case:
        return result.lower()
    else:
        return result


def get_shared_storage_ids_by_type(shared_storage_infos: dict, storage_type: SharedStorageType):
    """Return shared storage ids from the given list for the given type."""
    return ",".join(storage_mapping.id for storage_mapping in shared_storage_infos[storage_type])


def dict_to_cfn_tags(tags: dict):
    """Convert a dictionary to a list of CfnTag."""
    return [CfnTag(key=key, value=value) for key, value in tags.items()] if tags else []


def get_cluster_tags(stack_name: str, raw_dict: bool = False):
    """Return a list of cluster tags to be used for all the resources."""
    tags = {PCLUSTER_CLUSTER_NAME_TAG: stack_name}
    return tags if raw_dict else dict_to_cfn_tags(tags)


def get_custom_tags(config: Union[BaseClusterConfig, SlurmQueue, SlurmComputeResource], raw_dict: bool = False):
    """Return a list of tags set by the user."""
    custom_tags = config.get_tags()
    tags = {tag.key: tag.value for tag in custom_tags} if custom_tags else {}
    return tags if raw_dict else dict_to_cfn_tags(tags)


def get_default_instance_tags(
    stack_name: str,
    config: BaseClusterConfig,
    node: Union[HeadNode, LoginNodesPool, BaseComputeResource],
    node_type: str,
    shared_storage_infos: dict,
    raw_dict: bool = False,
):
    """Return a list of default tags to be used for instances."""
    tags = {
        **get_cluster_tags(stack_name, raw_dict=True),
        "Name": node_type,
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
            efs=len(shared_storage_infos[SharedStorageType.EFS]),
            multiebs=len(shared_storage_infos[SharedStorageType.EBS]),
            raid=len(shared_storage_infos[SharedStorageType.RAID]),
            fsx=len(shared_storage_infos[SharedStorageType.FSX]),
        ),
    }
    if config.is_intel_hpc_platform_enabled:
        tags["parallelcluster:intel-hpc"] = "enable_intel_hpc_platform=true"
    return tags if raw_dict else dict_to_cfn_tags(tags)


def get_default_volume_tags(stack_name: str, node_type: str, raw_dict: bool = False):
    """Return a list of default tags to be used for volumes."""
    tags = {
        **get_cluster_tags(stack_name, raw_dict=True),
        PCLUSTER_NODE_TYPE_TAG: node_type,
    }
    return tags if raw_dict else dict_to_cfn_tags(tags)


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


def get_queue_security_groups_full(managed_compute_security_group: ec2.CfnSecurityGroup, queue: BaseQueue):
    """Return full security groups to be used for the queue, default plus additional ones."""
    queue_security_groups = []

    # Default security groups, created by us or provided by the user
    if queue.networking.security_groups:
        queue_security_groups.extend(queue.networking.security_groups)
    else:
        queue_security_groups.append(managed_compute_security_group.ref)

    # Additional security groups
    if queue.networking.additional_security_groups:
        queue_security_groups.extend(queue.networking.additional_security_groups)

    return queue_security_groups


def get_login_nodes_security_groups_full(
    managed_login_security_group: ec2.CfnSecurityGroup,
    pool: LoginNodesPool,
):
    """Return full security groups to be used for the login node, default plus additional ones."""
    login_nodes_security_groups = []

    # Default security groups, created by us or provided by the user
    if pool.networking.security_groups:
        login_nodes_security_groups.extend(pool.networking.security_groups)
    else:
        login_nodes_security_groups.append(managed_login_security_group.ref)

    # Additional security groups
    if pool.networking.additional_security_groups:
        login_nodes_security_groups.extend(pool.networking.additional_security_groups)

    return login_nodes_security_groups


def add_cluster_iam_resource_prefix(stack_name, config, name: str, iam_type: str):
    """Return a path and Name prefix from the Resource prefix config option."""
    full_resource_path = None
    full_resource_name = None
    if config.iam and config.iam.resource_prefix:
        iam_path, iam_name_prefix = split_resource_prefix(config.iam.resource_prefix)
        if iam_name_prefix:
            # Creating a Globally Unique Hash using Region, Type, Name and stack name
            resource_hash = (
                sha256((name + stack_name + iam_type + config.region).encode("utf-8")).hexdigest()[:12].upper()
            )
            full_resource_name = iam_name_prefix + name + "-" + resource_hash
        if iam_path:
            full_resource_path = iam_path

    return full_resource_path, full_resource_name


def add_lambda_cfn_role(scope, config, function_id: str, statements: List[iam.PolicyStatement], has_vpc_config: bool):
    """Return a CfnRole to be used for a Lambda function."""
    role_path, role_name = add_cluster_iam_resource_prefix(
        config.cluster_name, config, name=f"{function_id}Role", iam_type="AWS::IAM::Role"
    )
    _, policy_name = add_cluster_iam_resource_prefix(
        config.cluster_name, config, "LambdaPolicy", iam_type="AWS::IAM::Policy"
    )

    role_id = f"{function_id}Role" if role_name else f"{function_id}FunctionExecutionRole"

    return iam.CfnRole(
        scope,
        role_id,
        path=role_path or IAM_ROLE_PATH,
        role_name=role_name,
        assume_role_policy_document=get_assume_role_policy_document("lambda.amazonaws.com"),
        policies=[
            iam.CfnRole.PolicyProperty(
                policy_document=iam.PolicyDocument(statements=statements),
                policy_name=policy_name or "LambdaPolicy",
            ),
        ],
        managed_policy_arns=[Fn.sub(LAMBDA_VPC_ACCESS_MANAGED_POLICY)] if has_vpc_config else None,
    )


def apply_permissions_boundary(boundary, scope):
    """Apply a permissions boundary to all IAM roles defined in the scope."""
    if boundary:
        boundary = ManagedPolicy.from_managed_policy_arn(scope, "Boundary", boundary)
        PermissionsBoundary.of(scope).apply(boundary)


def scheduler_is_slurm(config: BaseClusterConfig):
    return config.scheduling.scheduler == "slurm"


def generate_launch_template_version_cfn_parameter_hash(queue, compute_resource):
    """
    Generate 16 characters hash for compute fleet launch template version cfn parameter.

    :param queue
    :param compute_resource
    :return: 16 chars string e.g. 2238a84ac8a74529
    """
    # A nosec comment is appended to the following line in order to disable the B324 check.
    # The sha1 is used just as a hashing function.
    # [B324:hashlib] Use of weak MD4, MD5, or SHA1 hash for security. Consider usedforsecurity=False
    return sha1((queue + compute_resource).encode()).hexdigest()[0:16].capitalize()  # nosec nosemgrep


class NodeIamResourcesBase(Construct):
    """Abstract construct defining IAM resources for a cluster node."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        config: BaseClusterConfig,
        node: Union[HeadNode, BaseQueue, LoginNodesPool],
        shared_storage_infos: dict,
        name: str,
    ):
        super().__init__(scope, id)
        self._config = config
        self.instance_role = None

        self._add_role_and_policies(node, shared_storage_infos, name)

    def _add_role_and_policies(
        self,
        node: Union[HeadNode, BaseQueue, LoginNodesPool],
        shared_storage_infos: dict,
        name: str,
    ):
        """Create role and policies for the given node/queue."""
        suffix = create_hash_suffix(name)
        if node.instance_profile:
            # If existing InstanceProfile provided, do not create InstanceRole
            self.instance_profile = get_resource_name_from_resource_arn(node.instance_profile)
        elif node.instance_role:
            node_role_ref = get_resource_name_from_resource_arn(node.instance_role)
            self.instance_profile = self._add_instance_profile(node_role_ref, f"InstanceProfile{suffix}")
        else:
            self.instance_role = self._add_node_role(node, f"Role{suffix}")

            # ParallelCluster Policies
            self._add_pcluster_policies_to_role(
                self.instance_role.ref, shared_storage_infos, f"ParallelClusterPolicies{suffix}"
            )

            # Custom Cookbook S3 url policy
            if self._condition_custom_cookbook_with_s3_url():
                self._add_custom_cookbook_policies_to_role(self.instance_role.ref, f"CustomCookbookPolicies{suffix}")

            # S3 Access Policies
            if isinstance(node, (BaseQueue, HeadNode)) and self._condition_create_s3_access_policies(node):
                self._add_s3_access_policies_to_role(node, self.instance_role.ref, f"S3AccessPolicies{suffix}")

            # Head node Instance Profile
            self.instance_profile = self._add_instance_profile(self.instance_role.ref, f"InstanceProfile{suffix}")

    def _add_instance_profile(self, role_ref: str, name: str):
        instance_profile_path, instance_profile_name = add_cluster_iam_resource_prefix(
            self._config.cluster_name, self._config, name, iam_type="AWS::IAM::InstanceProfile"
        )
        return iam.CfnInstanceProfile(
            Stack.of(self),
            name,
            roles=[role_ref],
            path=self._cluster_scoped_iam_path(iam_path=instance_profile_path),
            instance_profile_name=instance_profile_name,
        ).ref

    def _add_node_role(self, node: Union[HeadNode, BaseQueue, LoginNodesPool], name: str):
        role_path, role_name = add_cluster_iam_resource_prefix(
            self._config.cluster_name, self._config, name, iam_type="AWS::IAM::Role"
        )
        additional_iam_policies = set(node.iam.additional_iam_policy_arns)
        if self._config.monitoring.logs.cloud_watch.enabled:
            additional_iam_policies.add(policy_name_to_arn("CloudWatchAgentServerPolicy"))
        return iam.CfnRole(
            Stack.of(self),
            name,
            path=self._cluster_scoped_iam_path(iam_path=role_path),
            managed_policy_arns=list(additional_iam_policies),
            assume_role_policy_document=get_assume_role_policy_document("ec2.{0}".format(Stack.of(self).url_suffix)),
            role_name=role_name,
        )

    def _add_pcluster_policies_to_role(self, role_ref: str, shared_storage_infos: dict, name: str):
        _, policy_name = add_cluster_iam_resource_prefix(
            self._config.cluster_name, self._config, "parallelcluster", iam_type="AWS::IAM::Policy"
        )
        common_policies = []
        if self._config.scheduling.scheduler != "awsbatch":
            efs_with_iam_authorization_arns = self._get_efs_with_iam_authorization_arns(shared_storage_infos)
            if efs_with_iam_authorization_arns:
                common_policies.append(
                    iam.PolicyStatement(
                        sid="Efs",
                        actions=[
                            "elasticfilesystem:ClientMount",
                            "elasticfilesystem:ClientRootAccess",
                            "elasticfilesystem:ClientWrite",
                        ],
                        effect=iam.Effect.ALLOW,
                        resources=efs_with_iam_authorization_arns,
                    ),
                )
        iam.CfnPolicy(
            Stack.of(self),
            name,
            policy_name=policy_name or "parallelcluster",
            policy_document=iam.PolicyDocument(statements=self._build_policy() + common_policies),
            roles=[role_ref],
        )

    def _get_efs_with_iam_authorization_arns(self, shared_storage_infos):
        return [
            self._format_arn(
                service="elasticfilesystem",
                resource=f"file-system/{efs_id}",
                region=Stack.of(self).region,
                account=Stack.of(self).account,
            )
            for efs_id, efs_storage in shared_storage_infos[SharedStorageType.EFS]
            if efs_storage.iam_authorization
        ]

    def _condition_custom_cookbook_with_s3_url(self):
        try:
            return self._config.dev_settings.cookbook.chef_cookbook.startswith("s3://")
        except AttributeError:
            return False

    def _condition_create_s3_access_policies(self, node: Union[HeadNode, BaseQueue, LoginNodesPool]):
        return node.iam and node.iam.s3_access

    def _add_custom_cookbook_policies_to_role(self, role_ref: str, name: str):
        bucket_info = parse_bucket_url(self._config.dev_settings.cookbook.chef_cookbook)
        bucket_name = bucket_info.get("bucket_name")
        object_key = bucket_info.get("object_key")
        iam.CfnPolicy(
            Stack.of(self),
            name,
            policy_name="CustomCookbookS3Url",
            policy_document=iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        actions=["s3:GetObject"],
                        effect=iam.Effect.ALLOW,
                        resources=[
                            self._format_arn(
                                region="", service="s3", account="", resource=bucket_name, resource_name=object_key
                            )
                        ],
                    ),
                    iam.PolicyStatement(
                        actions=["s3:GetBucketLocation"],
                        effect=iam.Effect.ALLOW,
                        resources=[self._format_arn(service="s3", resource=bucket_name, region="", account="")],
                    ),
                ]
            ),
            roles=[role_ref],
        )

    def _add_s3_access_policies_to_role(
        self, node: Union[HeadNode, BaseQueue, LoginNodesPool], role_ref: str, name: str
    ):
        """Attach S3 policies to given role."""
        read_only_s3_resources = []
        read_write_s3_resources = []
        for s3_access in node.iam.s3_access:
            for resource in s3_access.resource_regex:
                arn = self._format_arn(service="s3", resource=resource, region="", account="")
                if s3_access.enable_write_access:
                    read_write_s3_resources.append(arn)
                else:
                    read_only_s3_resources.append(arn)
        _, policy_name = add_cluster_iam_resource_prefix(
            self._config.cluster_name, self._config, "S3Access", iam_type="AWS::IAM::Policy"
        )

        s3_access_policy = iam.CfnPolicy(
            Stack.of(self),
            name,
            policy_document=iam.PolicyDocument(statements=[]),
            roles=[role_ref],
            policy_name=policy_name or "S3Access",
        )

        if read_only_s3_resources:
            s3_access_policy.policy_document.add_statements(
                iam.PolicyStatement(
                    sid="S3Read",
                    effect=iam.Effect.ALLOW,
                    actions=["s3:Get*", "s3:List*"],
                    resources=read_only_s3_resources,
                )
            )

        if read_write_s3_resources:
            s3_access_policy.policy_document.add_statements(
                iam.PolicyStatement(
                    sid="S3ReadWrite", effect=iam.Effect.ALLOW, actions=["s3:*"], resources=read_write_s3_resources
                )
            )

    def _cluster_scoped_iam_path(self, iam_path=None):
        """Return a path to be associated with IAM roles and instance profiles."""
        if iam_path:
            return f"{iam_path}{Stack.of(self).stack_name}/"
        else:
            return f"{IAM_ROLE_PATH}{Stack.of(self).stack_name}/"

    def _format_arn(self, **kwargs):
        return Stack.of(self).format_arn(**kwargs)

    @abc.abstractmethod
    def _build_policy(self) -> List[iam.PolicyStatement]:
        pass


class HeadNodeIamResources(NodeIamResourcesBase):
    """Construct defining IAM resources for the head node."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        config: BaseClusterConfig,
        node: Union[HeadNode, BaseQueue, LoginNodesPool],
        shared_storage_infos: dict,
        name: str,
        cluster_bucket: S3Bucket,
    ):
        self._cluster_bucket = cluster_bucket
        super().__init__(scope, id, config, node, shared_storage_infos, name)

    def _build_policy(self) -> List[iam.PolicyStatement]:
        policy = [
            iam.PolicyStatement(
                sid="Ec2",
                actions=[
                    "ec2:DescribeInstanceAttribute",
                    "ec2:DescribeInstances",
                    "ec2:DescribeInstanceStatus",
                    "ec2:DescribeVolumes",
                ],
                effect=iam.Effect.ALLOW,
                resources=["*"],
            ),
            iam.PolicyStatement(
                sid="Ec2TagsAndVolumes",
                actions=["ec2:AttachVolume", "ec2:CreateTags", "ec2:DetachVolume"],
                effect=iam.Effect.ALLOW,
                resources=[
                    self._format_arn(
                        service="ec2",
                        resource="instance/*",
                        region=Stack.of(self).region,
                        account=Stack.of(self).account,
                    ),
                    self._format_arn(
                        service="ec2",
                        resource="volume/*",
                        region=Stack.of(self).region,
                        account=Stack.of(self).account,
                    ),
                ],
            ),
            iam.PolicyStatement(
                sid="S3GetObj",
                actions=["s3:GetObject"],
                effect=iam.Effect.ALLOW,
                resources=[
                    self._format_arn(
                        service="s3",
                        resource="{0}-aws-parallelcluster/*".format(Stack.of(self).region),
                        region="",
                        account="",
                    )
                ],
            ),
            iam.PolicyStatement(
                sid="ResourcesS3Bucket",
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject", "s3:GetObjectVersion", "s3:GetBucketLocation", "s3:ListBucket"],
                resources=[
                    self._format_arn(service="s3", resource=self._cluster_bucket.name, region="", account=""),
                    self._format_arn(
                        service="s3",
                        resource=f"{self._cluster_bucket.name}/{self._cluster_bucket.artifact_directory}/*",
                        region="",
                        account="",
                    ),
                ],
            ),
            iam.PolicyStatement(
                sid="CloudFormation",
                actions=[
                    "cloudformation:DescribeStacks",
                    "cloudformation:DescribeStackResource",
                    "cloudformation:SignalResource",
                ],
                effect=iam.Effect.ALLOW,
                resources=[
                    self._format_arn(service="cloudformation", resource=f"stack/{Stack.of(self).stack_name}/*"),
                    self._format_arn(service="cloudformation", resource=f"stack/{Stack.of(self).stack_name}-*/*"),
                ],
            ),
            iam.PolicyStatement(
                sid="DcvLicense",
                actions=[
                    "s3:GetObject",
                ],
                effect=iam.Effect.ALLOW,
                resources=[
                    self._format_arn(
                        service="s3",
                        resource="dcv-license.{0}/*".format(Stack.of(self).region),
                        region="",
                        account="",
                    )
                ],
            ),
        ]

        if (
            self._config.scheduling.scheduler == "slurm"
            and self._config.scheduling.settings
            and self._config.scheduling.settings.munge_key_secret_arn
        ):
            policy.extend(
                [
                    iam.PolicyStatement(
                        sid="SecretsManager",
                        actions=["secretsmanager:GetSecretValue"],
                        effect=iam.Effect.ALLOW,
                        resources=[self._config.scheduling.settings.munge_key_secret_arn],
                    ),
                ]
            )

            if self._config.login_nodes:
                policy.extend(
                    [
                        iam.PolicyStatement(
                            sid="ElasticLoadBalancingDescribe",
                            actions=[
                                "elasticloadbalancing:DescribeLoadBalancers",
                                "elasticloadbalancing:DescribeTags",
                                "elasticloadbalancing:DescribeTargetGroups",
                                "elasticloadbalancing:DescribeTargetHealth",
                            ],
                            effect=iam.Effect.ALLOW,
                            resources=["*"],
                        ),
                    ]
                )

        if self._config.scheduling.scheduler != "awsbatch":
            policy.extend(
                [
                    iam.PolicyStatement(
                        sid="EC2Terminate",
                        actions=["ec2:TerminateInstances"],
                        effect=iam.Effect.ALLOW,
                        resources=["*"],
                        conditions={
                            "StringEquals": {f"ec2:ResourceTag/{PCLUSTER_CLUSTER_NAME_TAG}": Stack.of(self).stack_name}
                        },
                    ),
                    iam.PolicyStatement(
                        sid="EC2RunInstancesCreateFleet",
                        actions=["ec2:RunInstances", "ec2:CreateFleet"],
                        effect=iam.Effect.ALLOW,
                        resources=[
                            self._format_arn(service="ec2", resource=f"subnet/{subnet_id}")
                            for subnet_id in self._config.compute_subnet_ids
                        ]
                        + [
                            self._format_arn(service="ec2", resource="fleet/*"),
                            self._format_arn(service="ec2", resource="network-interface/*"),
                            self._format_arn(service="ec2", resource="instance/*"),
                            self._format_arn(service="ec2", resource="volume/*"),
                            self._format_arn(service="ec2", resource=f"key-pair/{self._config.head_node.ssh.key_name}"),
                            self._format_arn(service="ec2", resource="security-group/*"),
                            self._format_arn(service="ec2", resource="launch-template/*"),
                            self._format_arn(service="ec2", resource="placement-group/*"),
                        ]
                        + [
                            self._format_arn(service="ec2", resource=f"image/{queue_ami}", account="")
                            for _, queue_ami in self._config.image_dict.items()
                        ],
                    ),
                    iam.PolicyStatement(
                        sid="EC2DescribeCapacityReservations",
                        actions=["ec2:DescribeCapacityReservations"],
                        effect=iam.Effect.ALLOW,
                        resources=["*"],
                    ),
                    iam.PolicyStatement(
                        sid="PassRole",
                        actions=["iam:PassRole"],
                        effect=iam.Effect.ALLOW,
                        resources=self._generate_head_node_pass_role_resources(),
                    ),
                    iam.PolicyStatement(
                        sid="DynamoDBTable",
                        actions=["dynamodb:UpdateItem", "dynamodb:PutItem", "dynamodb:GetItem"],
                        effect=iam.Effect.ALLOW,
                        resources=[
                            self._format_arn(
                                service="dynamodb",
                                resource=f"table/{PCLUSTER_DYNAMODB_PREFIX}{Stack.of(self).stack_name}",
                            )
                        ],
                    ),
                ]
            )

            self._add_compute_console_output_policy_statement(policy)

            capacity_reservation_ids = self._config.capacity_reservation_ids

            if capacity_reservation_ids:
                policy.append(
                    iam.PolicyStatement(
                        sid="AllowRunningReservedCapacity",
                        actions=["ec2:RunInstances"],
                        effect=iam.Effect.ALLOW,
                        resources=self._config.capacity_reservation_arns,
                    )
                )
            capacity_reservation_resource_group_arns = self._config.capacity_reservation_resource_group_arns
            if capacity_reservation_resource_group_arns:
                policy.extend(
                    [
                        iam.PolicyStatement(
                            sid="AllowManagingReservedCapacity",
                            actions=["ec2:RunInstances", "ec2:CreateFleet", "resource-groups:ListGroupResources"],
                            effect=iam.Effect.ALLOW,
                            resources=capacity_reservation_resource_group_arns,
                        )
                    ]
                )

        if self._config.directory_service:
            password_secret_arn = Arn.split(
                self._config.directory_service.password_secret_arn, ArnFormat.COLON_RESOURCE_NAME
            )
            policy.append(
                iam.PolicyStatement(
                    sid="AllowGettingDirectorySecretValue",
                    actions=[
                        "secretsmanager:GetSecretValue"
                        if password_secret_arn.service == "secretsmanager"
                        else "ssm:GetParameter"
                        if password_secret_arn.service == "ssm"
                        else None
                    ],
                    effect=iam.Effect.ALLOW,
                    resources=[self._config.directory_service.password_secret_arn],
                )
            )

        if self._config.scheduling.scheduler == "slurm" and self._config.scheduling.settings.database:
            policy.append(
                iam.PolicyStatement(
                    sid="AllowGettingSlurmDbSecretValue",
                    actions=["secretsmanager:GetSecretValue"],
                    effect=iam.Effect.ALLOW,
                    resources=[self._config.scheduling.settings.database.password_secret_arn],
                )
            )

        return policy

    def _add_compute_console_output_policy_statement(self, policy):
        if self._config.monitoring.logs.cloud_watch.enabled:
            queue_names = [queue.name for queue in self._config.scheduling.queues]
            policy.append(
                iam.PolicyStatement(
                    sid="EC2GetComputeConsoleOutput",
                    actions=["ec2:GetConsoleOutput"],
                    effect=iam.Effect.ALLOW,
                    resources=[self._format_arn(service="ec2", resource="instance/*")],
                    conditions={
                        "StringEquals": {
                            "aws:ResourceTag/parallelcluster:queue-name": queue_names,
                            "aws:ResourceTag/parallelcluster:node-type": "Compute",
                            "aws:ResourceTag/parallelcluster:cluster-name": Stack.of(self).stack_name,
                        }
                    },
                )
            )

    def _generate_head_node_pass_role_resources(self):
        """Return a unique list of ARNs that the head node should be able to use when calling PassRole."""
        resource_iam_path, _ = add_cluster_iam_resource_prefix(
            self._config.cluster_name, self._config, "", iam_type="AWS::IAM::Role"
        )
        default_pass_role_resource = self._format_arn(
            service="iam",
            region="",
            resource=f"role{self._cluster_scoped_iam_path(iam_path=resource_iam_path)}*",
        )

        # If there are any queues where a custom instance role was specified,
        # enable the head node to pass permissions to those roles.
        custom_queue_role_arns = {
            arn for queue in self._config.scheduling.queues for arn in queue.iam.instance_role_arns
        }
        if custom_queue_role_arns:
            pass_role_resources = custom_queue_role_arns

            # Include the default IAM role path for the queues that
            # aren't using a custom instance role.
            queues_without_custom_roles = [
                queue for queue in self._config.scheduling.queues if not queue.iam.instance_role_arns
            ]
            if any(queues_without_custom_roles):
                pass_role_resources.add(default_pass_role_resource)
        else:
            pass_role_resources = {default_pass_role_resource}
        return list(pass_role_resources)


class LoginNodesIamResources(NodeIamResourcesBase):
    """Construct defining IAM resources for a login node."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        config: BaseClusterConfig,
        node: Union[HeadNode, BaseQueue, LoginNodesPool],
        shared_storage_infos: dict,
        name: str,
        auto_scaling_group_name: str,
    ):
        self._auto_scaling_group_name = auto_scaling_group_name
        super().__init__(scope, id, config, node, shared_storage_infos, name)

    def _build_policy(self) -> List[iam.PolicyStatement]:
        return [
            iam.PolicyStatement(
                sid="Ec2",
                actions=["ec2:DescribeInstanceAttribute"],
                effect=iam.Effect.ALLOW,
                resources=["*"],
            ),
            iam.PolicyStatement(
                sid="S3GetObj",
                actions=["s3:GetObject"],
                effect=iam.Effect.ALLOW,
                resources=[
                    self._format_arn(
                        service="s3",
                        resource="{0}-aws-parallelcluster/*".format(Stack.of(self).region),
                        region="",
                        account="",
                    )
                ],
            ),
            iam.PolicyStatement(
                sid="Autoscaling",
                actions=[
                    "autoscaling:CompleteLifecycleAction",
                ],
                effect=iam.Effect.ALLOW,
                resources=[
                    self._format_arn(
                        service="autoscaling",
                        resource=f"autoScalingGroup:*:autoScalingGroupName/{self._auto_scaling_group_name}",
                    )
                ],
            ),
        ]


class ComputeNodeIamResources(NodeIamResourcesBase):
    """Construct defining IAM resources for a compute node."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        config: BaseClusterConfig,
        node: Union[HeadNode, BaseQueue, LoginNodesPool],
        shared_storage_infos: dict,
        name: str,
    ):
        super().__init__(scope, id, config, node, shared_storage_infos, name)

    def _build_policy(self) -> List[iam.PolicyStatement]:
        return [
            iam.PolicyStatement(
                sid="Ec2",
                actions=[
                    "ec2:DescribeInstanceAttribute",
                ],
                effect=iam.Effect.ALLOW,
                resources=["*"],
            ),
            iam.PolicyStatement(
                sid="S3GetObj",
                actions=["s3:GetObject"],
                effect=iam.Effect.ALLOW,
                resources=[
                    self._format_arn(
                        service="s3",
                        resource="{0}-aws-parallelcluster/*".format(Stack.of(self).region),
                        region="",
                        account="",
                    )
                ],
            ),
        ]


def get_lambda_log_group_prefix(function_id: str):
    """Return the prefix of the log group associated to Lambda functions created using PclusterLambdaConstruct."""
    return f"log-group:/aws/lambda/{PCLUSTER_LAMBDA_PREFIX}{function_id}"


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

        function_name = f"{PCLUSTER_LAMBDA_PREFIX}{function_id}-{self._stack_unique_id()}"

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
            runtime="python3.9",
            timeout=timeout,
            vpc_config=awslambda.CfnFunction.VpcConfigProperty(
                security_group_ids=config.lambda_functions_vpc_config.security_group_ids,
                subnet_ids=config.lambda_functions_vpc_config.subnet_ids,
            )
            if config.lambda_functions_vpc_config
            else None,
        )

    def _stack_unique_id(self):
        return Fn.select(2, Fn.split("/", Stack.of(self).stack_id))

    def _format_arn(self, **kwargs):
        return Stack.of(self).format_arn(**kwargs)


class CdkLaunchTemplateBuilder(_LaunchTemplateBuilder):
    """Concrete class for building a CDK launch template."""

    def _block_device_mapping_for_ebs(self, device_name, volume):
        return ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
            device_name=device_name,
            ebs=ec2.CfnLaunchTemplate.EbsProperty(
                volume_size=volume.size,
                encrypted=volume.encrypted,
                volume_type=volume.volume_type,
                iops=volume.iops,
                throughput=volume.throughput,
                delete_on_termination=volume.delete_on_termination,
            ),
        )

    def _block_device_mapping_for_virt(self, device_name, virtual_name):
        return ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(device_name=device_name, virtual_name=virtual_name)

    def _instance_market_option(self, market_type, spot_instance_type, instance_interruption_behavior, max_price):
        return ec2.CfnLaunchTemplate.InstanceMarketOptionsProperty(
            market_type=market_type,
            spot_options=ec2.CfnLaunchTemplate.SpotOptionsProperty(
                spot_instance_type=spot_instance_type,
                instance_interruption_behavior=instance_interruption_behavior,
                max_price=max_price,
            ),
        )

    def _capacity_reservation(self, cr_target):
        return ec2.CfnLaunchTemplate.CapacityReservationSpecificationProperty(
            capacity_reservation_target=ec2.CfnLaunchTemplate.CapacityReservationTargetProperty(
                capacity_reservation_id=cr_target.capacity_reservation_id,
                capacity_reservation_resource_group_arn=cr_target.capacity_reservation_resource_group_arn,
            )
        )
