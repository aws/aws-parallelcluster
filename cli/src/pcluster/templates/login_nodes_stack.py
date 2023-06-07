from typing import Dict, List

from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_logs as logs
from aws_cdk.core import CfnTag, Fn, NestedStack, Stack
from constructs import Construct
from aws_cdk import aws_autoscaling as autoscaling
from pcluster.config.cluster_config import (
    SlurmClusterConfig,
    LoginNodes,
)
from pcluster.constants import (
    DEFAULT_EPHEMERAL_DIR,
    NODE_BOOTSTRAP_TIMEOUT,
    OS_MAPPING,
    PCLUSTER_COMPUTE_RESOURCE_NAME_TAG,
    PCLUSTER_QUEUE_NAME_TAG,
)
from pcluster.templates.cdk_builder_utils import (
    CdkLaunchTemplateBuilder,
    ComputeNodeIamResources,
    create_hash_suffix,
    dict_to_cfn_tags,
    get_common_user_data_env,
    get_custom_tags,
    get_default_instance_tags,
    get_default_volume_tags,
    get_queue_security_groups_full,
    get_shared_storage_ids_by_type,
    get_user_data_content,
    scheduler_is_slurm,
    to_comma_separated_string,
)
from pcluster.templates.slurm_builder import SlurmConstruct
from pcluster.utils import get_attr, get_http_tokens_setting


# class LoginNodesStack(NestedStack):
#     """Stack encapsulating a set of LoginNodes and the associated resources."""

# def __init__(
#         self,
#         scope: Construct,
#         id: str,
#         login_nodes: LoginNodes,
#         cluster_config: SlurmClusterConfig,
#         log_group: logs.CfnLogGroup,
#         shared_storage_infos: Dict,
#         shared_storage_mount_dirs: Dict,
#         shared_storage_attributes: Dict,
#         login_security_group,
#         cluster_hosted_zone,
#         head_eni,
# ):
#     super().__init__(scope, id)
#     self._login_nodes = login_nodes
#     self._config = cluster_config
#     self._shared_storage_infos = shared_storage_infos
#     self._shared_storage_mount_dirs = shared_storage_mount_dirs
#     self._shared_storage_attributes = shared_storage_attributes
#     self._login_security_group = login_security_group
#     self._log_group = log_group
#     self._cluster_hosted_zone = cluster_hosted_zone
#     self._head_eni = head_eni
#     self._launch_template_builder = CdkLaunchTemplateBuilder()
#     self._add_resources()
class LoginNodeStack(NestedStack):

    def __init__(self, scope: Construct, id: str, config, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # 创建基础安全组
        security_group = ec2.SecurityGroup(
            self,
            "LoginNodeSecurityGroup",
            vpc=ec2.Vpc.from_lookup(self, "VPC", vpc_id=config.vpc_id),  # 从配置获取VPC
            description="Allow ssh access to login nodes",
            allow_all_outbound=True  # 允许所有出站流量
        )

        # 允许来自任何地方的SSH连接
        security_group.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(22)
        )

        # 创建启动模板
        login_template = ec2.CfnLaunchTemplate(
            self,
            "LoginNodeLaunchTemplate",
            launch_template_name=f"{self.stack_name}-login",
            launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
                image_id=config.ami,  # 从配置获取AMI
                instance_type=config.instance_type,  # 从配置获取实例类型
                key_name=config.ssh_key,  # 从配置获取SSH密钥
                security_group_ids=[security_group.security_group_id],
                iam_instance_profile=ec2.CfnLaunchTemplate.IamInstanceProfileProperty(
                    arn=config.instance_profile  # 从配置获取IAM实例配置文件
                ),
                block_device_mappings=[
                    # 根据需求添加块设备映射
                ],
                network_interfaces=[
                    ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                        device_index=0,
                        associate_public_ip_address=config.assign_public_ip,
                        groups=[security_group.security_group_id],
                        subnet_id=config.subnet_id
                    )
                ],
                # 根据需求添加其他配置
            )
        )

        # 创建自动缩放组
        auto_scaling_group = autoscaling.AutoScalingGroup(
            self,
            "LoginNodeAutoScalingGroup",
            vpc=ec2.Vpc.from_lookup(self, "ASG-VPC", vpc_id=config.vpc_id),  # 从配置获取VPC
            instance_type=ec2.InstanceType.of(config.instance_type),  # 从配置获取实例类型
            machine_image=ec2.MachineImage.generic_linux({  # 使用通用Linux AMI
                self.region: config.ami  # 从配置获取AMI ID
            }),
            key_name=config.ssh_key,  # 从配置获取SSH密钥
            security_group=security_group,  # 使用我们前面创建的安全组
            desired_capacity=config.min_count,  # 从配置获取MinCount
            min_capacity=config.min_count,  # 从配置获取MinCount
            max_capacity=config.max_count,  # 从配置获取MaxCount
            vpc_subnets=ec2.SubnetSelection(subnet_name=config.subnet_name),  # 从配置获取子网
            launch_template=autoscaling.LaunchTemplate.from_launch_template_name(
                self,
                'LaunchTemplate',
                login_template.launch_template_name
            )
        )

    @property
    def stack_name(self):
        """Name of the CFN stack."""
        return Stack.of(self.nested_stack_parent).stack_name

    def _add_resources(self):
        self._add_login_node_iam_resources()
        self._add_placement_groups()
        self._add_launch_templates()

    def _add_placement_groups(self):
        self.managed_placement_groups = {}
        for pool in self._login_nodes.pools:
            for key in pool.get_managed_placement_group_keys():
                self.managed_placement_groups[key] = ec2.CfnPlacementGroup(
                    self,
                    f"PlacementGroup{create_hash_suffix(key)}",
                    strategy="cluster",
                )

    def _add_login_node_iam_resources(self):
        iam_resources = {}
        for pool in self._login_nodes.pools:
            iam_resources[pool.name] = LoginNodeIamResources(
                self,
                f"LoginNodeIamResources{pool.name}",
                self._config,
                pool,
                self._shared_storage_infos,
                pool.name,
            )
        self._login_instance_profiles = {k: v.instance_profile for k, v in iam_resources.items()}
        self.managed_login_instance_roles = {k: v.instance_role for k, v in iam_resources.items()}

    def _add_launch_templates(self):
        self.login_launch_templates = {}
        for pool in self._login_nodes.pools:
            pool_lt_security_groups = get_pool_security_groups_full(self._login_security_group, pool)
            self.login_launch_templates[pool.name] = self._add_login_resource_launch_template(
                pool,
                pool_lt_security_groups,
                self._get_placement_group_for_login_resource(pool, self.managed_placement_groups),
                self._login_instance_profiles,
                self._config.is_detailed_monitoring_enabled,
            )

    def _get_custom_login_resource_tags(self, login_nodes_config):
        """Login resource tags value on Cluster level tags if there are duplicated keys."""
        tags = get_custom_tags(self._config, raw_dict=True)
        login_resource_tags = get_custom_tags(login_nodes_config, raw_dict=True)
        return dict_to_cfn_tags({**tags, **login_resource_tags})

    def _add_login_node_pool_launch_template(
        self,
        login_nodes,
        login_nodes_pool,
        login_nodes_lt_security_groups,
        placement_group,
        instance_profiles,
        is_detailed_monitoring_enabled,
    ):
        login_node_lt_nw_interface = ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
            device_index=0,
            associate_public_ip_address=True,  # 调整此处
            interface_type=None,  # 调整此处
            groups=[self._login_node_security_group],  # 调整此处
            subnet_id=self._login_node_subnet_id  # 调整此处
        )

        self.login_node_launch_template = ec2.CfnLaunchTemplate(
            self,
            f"LoginNodeLaunchTemplate{login_nodes_pool.name}",
            launch_template_name=f"{self.stack_name}-LoginNode",
            launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
                block_device_mappings=self._launch_template_builder.get_block_device_mappings(
                    self._login_node_local_storage.root_volume, self._config.image.os  # 调整此处
                ),
                network_interfaces=[login_node_lt_nw_interface],
                image_id=self._login_node_image_id,  # 调整此处
                iam_instance_profile=ec2.CfnLaunchTemplate.IamInstanceProfileProperty(
                    name=self._login_node_instance_profile  # 调整此处
                ),
                instance_initiated_shutdown_behavior="terminate",
                user_data=Fn.base64(
                    Fn.sub(
                        get_user_data_content("../resources/login_node/user_data.sh"),  # 调整此处
                        {
                            # 调整此处，将根据您的user_data脚本定义变量
                        }
                    )
                ),
                tag_specifications=[
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="instance",
                        tags=get_default_instance_tags(
                            self.stack_name, self._config, None, "Login", self._shared_storage_infos  # 调整此处
                        ),
                    ),
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="volume",
                        tags=get_default_volume_tags(self.stack_name, "Login")  # 调整此处
                    ),
                ],
            ),
        )
