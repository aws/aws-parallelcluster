# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from botocore.exceptions import ClientError

from pcluster.cluster_model import ClusterModel
from pcluster.config import mappings
from pcluster.utils import InstanceTypeInfo, disable_ht_via_cpu_options


class SITClusterModel(ClusterModel):
    """SIT (Single Instance Type) cluster model."""

    def __init__(self):
        super(SITClusterModel, self).__init__("SIT")

    def get_cluster_section_definition(self):
        """Get the cluster section definition used by the cluster model."""
        return mappings.CLUSTER_SIT

    def get_start_command(self, pcluster_config):
        """Get the start command for a SIT cluster."""
        cluster_section = pcluster_config.get_section("cluster")
        if cluster_section.get_param_value("scheduler") == "awsbatch":
            from pcluster.cli_commands.start import AWSBatchStartCommand

            return AWSBatchStartCommand()
        else:
            from pcluster.cli_commands.start import SITStartCommand

            return SITStartCommand()

    def get_stop_command(self, pcluster_config):
        """Get the stop command for a SIT cluster."""
        cluster_section = pcluster_config.get_section("cluster")
        if cluster_section.get_param_value("scheduler") == "awsbatch":
            from pcluster.cli_commands.stop import AWSBatchStopCommand

            return AWSBatchStopCommand()
        else:
            from pcluster.cli_commands.stop import SITStopCommand

            return SITStopCommand()

    def test_configuration(self, pcluster_config):
        """
        Try to launch the requested instances (in dry-run mode) to verify configuration parameters.

        NOTE: The number of max instances is set to 1 because run_instances in dry-mode doesn't try to allocate the
        requested instances. The goal of the test is verify the provided configuration.
        """
        cluster_section = pcluster_config.get_section("cluster")
        vpc_section = pcluster_config.get_section("vpc")

        if (
            cluster_section.get_param_value("scheduler") == "awsbatch"
            or cluster_section.get_param_value("cluster_type") == "spot"
        ):
            return

        head_node_instance_type = cluster_section.get_param_value("master_instance_type")
        compute_instance_type = cluster_section.get_param_value("compute_instance_type")

        # Retrieve network parameters
        compute_subnet = vpc_section.get_param_value("compute_subnet_id")
        head_node_subnet = vpc_section.get_param_value("master_subnet_id")
        vpc_security_group = vpc_section.get_param_value("vpc_security_group_id")
        if not compute_subnet:
            compute_subnet = head_node_subnet
        security_groups_ids = []
        if vpc_security_group:
            security_groups_ids.append(vpc_security_group)

        # Initialize CpuOptions
        disable_hyperthreading = cluster_section.get_param_value("disable_hyperthreading")
        head_node_instance_type_info = InstanceTypeInfo.init_from_instance_type(head_node_instance_type)
        head_node_vcpus = head_node_instance_type_info.vcpus_count()
        head_node_threads_per_core = head_node_instance_type_info.default_threads_per_core()
        compute_instance_type_info = InstanceTypeInfo.init_from_instance_type(compute_instance_type)
        compute_vcpus = compute_instance_type_info.vcpus_count()
        compute_threads_per_core = compute_instance_type_info.default_threads_per_core()
        head_node_cpu_options = (
            {"CoreCount": head_node_vcpus // head_node_threads_per_core, "ThreadsPerCore": 1}
            if disable_hyperthreading and disable_ht_via_cpu_options(head_node_instance_type)
            else {}
        )
        compute_cpu_options = (
            {"CoreCount": compute_vcpus // compute_threads_per_core, "ThreadsPerCore": 1}
            if disable_hyperthreading and disable_ht_via_cpu_options(compute_instance_type)
            else {}
        )

        # Initialize Placement Group Logic
        placement_group = cluster_section.get_param_value("placement_group")
        placement = cluster_section.get_param_value("placement")
        head_node_placement_group = (
            {"GroupName": placement_group}
            if placement_group not in [None, "NONE", "DYNAMIC"] and placement == "cluster"
            else {}
        )
        compute_placement_group = (
            {"GroupName": placement_group} if placement_group not in [None, "NONE", "DYNAMIC"] else {}
        )

        try:
            cluster_ami_id = self._get_cluster_ami_id(pcluster_config)

            head_node_network_interfaces = self.build_launch_network_interfaces(
                network_interfaces_count=int(cluster_section.get_param_value("network_interfaces_count")[0]),
                use_efa=False,  # EFA is not supported on head node
                security_group_ids=security_groups_ids,
                subnet=head_node_subnet,
                use_public_ips=vpc_section.get_param_value("use_public_ips"),
            )

            tag_specifications = self._generate_tag_specifications_for_dry_run(pcluster_config)

            # Test head node configuration
            self._ec2_run_instance(
                pcluster_config,
                InstanceType=head_node_instance_type,
                MinCount=1,
                MaxCount=1,
                ImageId=cluster_ami_id,
                CpuOptions=head_node_cpu_options,
                NetworkInterfaces=head_node_network_interfaces,
                Placement=head_node_placement_group,
                DryRun=True,
                TagSpecifications=tag_specifications,
            )

            compute_network_interfaces_count = int(cluster_section.get_param_value("network_interfaces_count")[1])
            enable_efa = "compute" == cluster_section.get_param_value("enable_efa")
            # TODO: check if head node == compute subnet condition is to take into account
            use_public_ips = self.public_ips_in_compute_subnet(pcluster_config, compute_network_interfaces_count)

            network_interfaces = self.build_launch_network_interfaces(
                compute_network_interfaces_count,
                enable_efa,
                security_groups_ids,
                compute_subnet,
                use_public_ips,
            )

            # Test Compute Instances Configuration
            self._ec2_run_instance(
                pcluster_config,
                InstanceType=compute_instance_type,
                MinCount=1,
                MaxCount=1,
                ImageId=cluster_ami_id,
                CpuOptions=compute_cpu_options,
                Placement=compute_placement_group,
                NetworkInterfaces=network_interfaces,
                DryRun=True,
                TagSpecifications=tag_specifications,
            )
        except ClientError:
            pcluster_config.error("Unable to validate configuration parameters.")
