from typing import Dict

from aws_cdk import aws_ec2 as ec2
from aws_cdk.core import NestedStack, Stack
from constructs import Construct
from aws_cdk import aws_autoscaling as autoscaling
from pcluster.config.cluster_config import (
    SlurmClusterConfig,
    LoginNodesPools
)
from pcluster.templates.cdk_builder_utils import (
    CdkLaunchTemplateBuilder,
    LoginNodesIamResources,
    get_login_nodes_security_groups_full,
)
from pcluster.utils import get_http_tokens_setting


class LoginNodesStack(NestedStack):

    def __init__(
        self,
        scope: Construct,
        id: str,
        cluster_config: SlurmClusterConfig,
        shared_storage_infos: Dict,
        shared_storage_mount_dirs: Dict,
        shared_storage_attributes: Dict,
        login_security_group,
    ):
        super().__init__(scope, id)
        self._login_nodes = cluster_config.login_nodes
        self._config = cluster_config
        self._login_security_group = login_security_group
        self._launch_template_builder = CdkLaunchTemplateBuilder()
        self._shared_storage_infos = shared_storage_infos
        self._shared_storage_mount_dirs = shared_storage_mount_dirs
        self._shared_storage_attributes = shared_storage_attributes

        self._add_resources()

    @property
    def stack_name(self):
        """Name of the CFN stack."""
        return Stack.of(self.nested_stack_parent).stack_name

    def _add_resources(self):
        self._add_login_node_iam_resources()
        self._add_launch_templates()
        self._add_auto_scaling_groups()

    def _add_login_node_iam_resources(self):
        iam_resources = {}
        for pool in self._login_nodes.pools:
            iam_resources[pool.name] = LoginNodesIamResources(
                self,
                f"LoginNodeIamResources{pool.name}",
                self._config,
                pool,
                self._shared_storage_infos,
                pool.name,
            )
        self._login_nodes_instance_profiles = {k: v.instance_profile for k, v in iam_resources.items()}
        self.managed_login_nodes_instance_roles = {k: v.instance_role for k, v in iam_resources.items()}

    def _add_launch_templates(self):
        self.login_launch_templates = {}
        for pool in self._login_nodes.pools:
            pool_lt_security_groups = get_login_nodes_security_groups_full(
                self._login_security_group,
                pool,
            )
            self.login_launch_templates[pool.name] = self._add_login_nodes_pool_launch_template(
                pool,
                pool_lt_security_groups,
                self._login_nodes_instance_profiles,
            )

    def _add_auto_scaling_groups(self):
        self.login_nodes_auto_security_groups = {}
        for pool in self._login_nodes.pools:
            self.login_nodes_auto_scaling_groups[pool.name] = self._add_login_nodes_pool_auto_scaling_group(
                pool,
            )

    def _add_login_nodes_pool_launch_template(
        self,
        login_nodes_pool: LoginNodesPools,
        login_nodes_pool_lt_security_groups,
        login_nodes_instance_profiles,
    ):
        login_node_lt_nw_interface = ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
            device_index=0,
            interface_type=None,
            groups=login_nodes_pool_lt_security_groups,
            subnet_id=login_nodes_pool.networking.subnet_id
        )

        return ec2.CfnLaunchTemplate(
            self,
            f"LoginNodeLaunchTemplate{login_nodes_pool.name}",
            launch_template_name=f"{self.stack_name}-{login_nodes_pool.name}",
            launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
                image_id=login_nodes_pool.image.custom_ami,
                instance_type=login_nodes_pool.instance_type,
                key_name=login_nodes_pool.ssh.key_name,
                iam_instance_profile=ec2.CfnLaunchTemplate.IamInstanceProfileProperty(
                    name=login_nodes_instance_profiles[login_nodes_pool.name]
                ),
                metadata_options=ec2.CfnLaunchTemplate.MetadataOptionsProperty(
                    http_tokens=get_http_tokens_setting(self._config.imds.imds_support)
                ),
                network_interfaces=login_node_lt_nw_interface,
                # user_data=
                # block_device_mappings=
            )
        )

    def _add_login_nodes_pool_auto_scaling_group(
        self,
        login_nodes_pool: LoginNodesPools,
    ):
        auto_scaling_group = autoscaling.AutoScalingGroup(
            self,
            "LoginNodeAutoScalingGroup",
            vpc=ec2.Vpc.from_lookup(self, "ASG-VPC", vpc_id=self._config.vpc_id),
            instance_type=ec2.InstanceType.of(login_nodes_pool.instance_type),
            machine_image=ec2.MachineImage.generic_linux({
                self.region: login_nodes_pool.image.custom_ami
            }),
            key_name=login_nodes_pool.ssh.key_name,
            security_group=self._login_security_group,
            desired_capacity=login_nodes_pool.count,
            min_capacity=login_nodes_pool.count,
            max_capacity=login_nodes_pool.count,
            vpc_subnets=ec2.SubnetSelection(subnet_name=login_nodes_pool.networking.subnet_id),
        )

        return auto_scaling_group
