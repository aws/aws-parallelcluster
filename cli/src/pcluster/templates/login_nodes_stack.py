from typing import Dict

from aws_cdk import (
    aws_elasticloadbalancingv2 as elbv2,
    aws_autoscaling as autoscaling,
    aws_ec2 as ec2,
)
from aws_cdk.core import NestedStack, Stack
from constructs import Construct

from pcluster.config.cluster_config import LoginNodesPools, SlurmClusterConfig
from pcluster.templates.cdk_builder_utils import (
    CdkLaunchTemplateBuilder,
    LoginNodesIamResources,
    get_login_nodes_security_groups_full,
)
from pcluster.utils import get_http_tokens_setting


class LoginNodesStack(NestedStack):
    """Stack encapsulating a set of LoginNodes and the associated resources."""

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
        self._login_node_stack_id = id
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
        # get unique login nodes pools subnet id
        subnet_ids = set()
        for login_nodes_pool in self._login_nodes.pools:
            subnet_ids.add(login_nodes_pool.networking.subnet_id)
        self._pools_subnet_ids = list(subnet_ids)

        # get unique login nodes pools availability_zone
        availability_zones = set()
        for login_nodes_pool in self._login_nodes.pools:
            availability_zones.add(login_nodes_pool.networking.availability_zone)
        self._pools_availability_zones = list(availability_zones)

        self._vpc = ec2.Vpc.from_vpc_attributes(
            self,
            "VPC",
            vpc_id=self._config.vpc_id,
            availability_zones=self._pools_availability_zones,
        )
        self._add_login_node_iam_resources()
        self._add_launch_templates()
        self._login_nodes_target_group = self._add_login_nodes_target_group()
        self._login_nodes_load_balancer = self._add_login_nodes_load_balancer(self._login_nodes_target_group)
        self._add_auto_scaling_groups(self._login_nodes_target_group)

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

    def _add_login_nodes_pool_launch_template(
        self,
        login_nodes_pool: LoginNodesPools,
        login_nodes_pool_lt_security_groups,
        login_nodes_instance_profiles,
    ):
        login_node_lt_nw_interface = [
            ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                device_index=0,
                interface_type=None,
                groups=login_nodes_pool_lt_security_groups,
                subnet_id=login_nodes_pool.networking.subnet_id,
            )
        ]
        return ec2.CfnLaunchTemplate(
            self,
            f"LoginNodeLaunchTemplate{login_nodes_pool.name}",
            launch_template_name=f"{self.stack_name}-{login_nodes_pool.name}",
            launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
                image_id=self._config.login_nodes_ami[login_nodes_pool.name],
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
            ),
        )

    def _add_login_nodes_target_group(self):
        return elbv2.NetworkTargetGroup(
            self,
            f"{self.stack_name}-TargetGroup",
            health_check=elbv2.HealthCheck(
                port="22",
                protocol=elbv2.Protocol.TCP,
            ),
            port=22,
            protocol=elbv2.Protocol.TCP,
            target_group_name=f"{self.stack_name}-TargetGroup",
            target_type=elbv2.TargetType.INSTANCE,
            vpc=self._vpc,
        )

    def _add_login_nodes_load_balancer(
        self,
        target_group,
    ):
        login_nodes_load_balancer = elbv2.NetworkLoadBalancer(
            self,
            f"{self.stack_name}-LoadBalancer",
            vpc=self._vpc,
            internet_facing=True,
            vpc_subnets=ec2.SubnetSelection(
                subnets=[
                    ec2.Subnet.from_subnet_id(self, f"LoginNodesSubnet{i}", subnet_id)
                    for i, subnet_id in enumerate(self._pools_subnet_ids)
                ]
            ),
        )

        listener = login_nodes_load_balancer.add_listener("LoginNodeListener", port=22)
        listener.add_target_groups("LoginNodeListenerTargets", target_group)
        return login_nodes_load_balancer

    def _add_auto_scaling_groups(self, login_nodes_target_group):
        self.login_nodes_auto_scaling_groups = {}
        for pool in self._login_nodes.pools:
            self.login_nodes_auto_scaling_groups[pool.name] = self._add_login_nodes_pool_auto_scaling_group(
                pool,
                login_nodes_target_group,
            )

    def _add_login_nodes_pool_auto_scaling_group(
        self,
        login_nodes_pool: LoginNodesPools,
        login_nodes_target_group,
    ):
        launch_template_specification = autoscaling.CfnAutoScalingGroup.LaunchTemplateSpecificationProperty(
            launch_template_id=self.login_launch_templates[login_nodes_pool.name].ref,
            version=self.login_launch_templates[login_nodes_pool.name].attr_latest_version_number,
        )

        auto_scaling_group = autoscaling.CfnAutoScalingGroup(
            self,
            f"{self._login_node_stack_id}-AutoScalingGroup",
            launch_template=launch_template_specification,
            min_size=str(login_nodes_pool.count),
            max_size=str(login_nodes_pool.count),
            desired_capacity=str(login_nodes_pool.count),
            target_group_arns=[login_nodes_target_group.node.default_child.ref],
            vpc_zone_identifier=[login_nodes_pool.networking.subnet_id],
        )

        return auto_scaling_group
