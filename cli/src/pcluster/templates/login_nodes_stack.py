from typing import Dict

from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk.core import Construct, NestedStack, Stack

from pcluster.config.cluster_config import SlurmClusterConfig
from pcluster.templates.cdk_builder_utils import (
    CdkLaunchTemplateBuilder,
    LoginNodesIamResources,
    get_default_instance_tags,
    get_default_volume_tags,
    get_login_nodes_security_groups_full,
)
from pcluster.utils import get_http_tokens_setting


class Pool(Construct):
    """Construct defining Login Nodes Pool specific resources."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        pool,
        config,
        shared_storage_infos,
        shared_storage_mount_dirs: Dict,
        shared_storage_attributes: Dict,
        login_security_group,
        login_nodes_target_group,
        stack_name,
    ):
        super().__init__(scope, id)
        self._pool = pool
        self._config = config
        self._login_nodes_stack_id = id
        self._shared_storage_infos = shared_storage_infos
        self._shared_storage_mount_dirs = shared_storage_mount_dirs
        self._shared_storage_attributes = shared_storage_attributes
        self._login_security_group = login_security_group
        self._login_nodes_target_group = login_nodes_target_group
        self.stack_name = stack_name

        self._add_resources()

    def _add_resources(self):
        self._add_login_node_iam_resources()
        self._launch_template = self._add_login_nodes_pool_launch_template()
        self._add_login_nodes_pool_auto_scaling_group()

    def _add_login_node_iam_resources(self):
        self._iam_resource = LoginNodesIamResources(
            self,
            f"LoginNodeIamResources{self._pool.name}",
            self._config,
            self._pool,
            self._shared_storage_infos,
            self._pool.name,
        )
        self._instance_profile = self._iam_resource.instance_profile
        self._instance_role = self._iam_resource.instance_role

    def _add_login_nodes_pool_launch_template(self):
        login_nodes_pool_lt_security_groups = get_login_nodes_security_groups_full(
            self._login_security_group,
            self._pool,
        )
        login_nodes_pool_lt_nw_interface = [
            ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                device_index=0,
                interface_type=None,
                groups=login_nodes_pool_lt_security_groups,
                subnet_id=self._pool.networking.subnet_id,
            )
        ]
        return ec2.CfnLaunchTemplate(
            self,
            f"LoginNodeLaunchTemplate{self._pool.name}",
            launch_template_name=f"{self.stack_name}-{self._pool.name}",
            launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
                image_id=self._config.login_nodes_ami[self._pool.name],
                instance_type=self._pool.instance_type,
                key_name=self._pool.ssh.key_name,
                iam_instance_profile=ec2.CfnLaunchTemplate.IamInstanceProfileProperty(name=self._instance_profile),
                metadata_options=ec2.CfnLaunchTemplate.MetadataOptionsProperty(
                    http_tokens=get_http_tokens_setting(self._config.imds.imds_support)
                ),
                network_interfaces=login_nodes_pool_lt_nw_interface,
                # user_data=
                # block_device_mappings=
                tag_specifications=[
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="instance",
                        tags=get_default_instance_tags(
                            self.stack_name, self._config, self._pool, "LoginNode", self._shared_storage_infos
                        )
                        # +
                        # + custom tags for instance
                    ),
                    ec2.CfnLaunchTemplate.TagSpecificationProperty(
                        resource_type="volume",
                        tags=get_default_volume_tags(self.stack_name, "LoginNode")
                        # +
                        # + custom tags for volume
                    ),
                ],
            ),
        )

    def _add_login_nodes_pool_auto_scaling_group(self):
        launch_template_specification = autoscaling.CfnAutoScalingGroup.LaunchTemplateSpecificationProperty(
            launch_template_id=self._launch_template.ref,
            version=self._launch_template.attr_latest_version_number,
        )

        auto_scaling_group = autoscaling.CfnAutoScalingGroup(
            self,
            f"{self._login_nodes_stack_id}-AutoScalingGroup",
            launch_template=launch_template_specification,
            min_size=str(self._pool.count),
            max_size=str(self._pool.count),
            desired_capacity=str(self._pool.count),
            target_group_arns=[self._login_nodes_target_group.node.default_child.ref],
            vpc_zone_identifier=[self._pool.networking.subnet_id],
        )

        return auto_scaling_group


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
        subnet_ids = set(pool.networking.subnet_id for pool in self._login_nodes.pools)
        self._pools_subnet_ids = list(subnet_ids)

        # get unique login nodes pools availability_zone
        availability_zones = set(pool.networking.availability_zone for pool in self._login_nodes.pools)
        self._pools_availability_zones = list(availability_zones)

        self._vpc = ec2.Vpc.from_vpc_attributes(
            self,
            "VPC",
            vpc_id=self._config.vpc_id,
            availability_zones=self._pools_availability_zones,
        )
        self._login_nodes_target_group = self._add_login_nodes_target_group()
        self._login_nodes_load_balancer = self._add_login_nodes_load_balancer(self._login_nodes_target_group)

        self.pools = {}
        for pool in self._login_nodes.pools:
            pool_construct = Pool(
                self,
                f"Pool{pool.name}",
                pool,
                self._config,
                self._shared_storage_infos,
                self._shared_storage_mount_dirs,
                self._shared_storage_attributes,
                self._login_security_group,
                self._login_nodes_target_group,
                self.stack_name,
            )
            self.pools[pool.name] = pool_construct

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
