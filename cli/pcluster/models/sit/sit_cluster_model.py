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
from pcluster.utils import disable_ht_via_cpu_options, get_default_threads_per_core, get_instance_vcpus


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
            not cluster_section
            or cluster_section.get_param_value("scheduler") == "awsbatch"
            or cluster_section.get_param_value("cluster_type") == "spot"
            or not vpc_section
        ):
            return

        master_instance_type = cluster_section.get_param_value("master_instance_type")
        compute_instance_type = cluster_section.get_param_value("compute_instance_type")

        # Retrieve network parameters
        compute_subnet = vpc_section.get_param_value("compute_subnet_id")
        master_subnet = vpc_section.get_param_value("master_subnet_id")
        vpc_security_group = vpc_section.get_param_value("vpc_security_group_id")
        if not compute_subnet:
            compute_subnet = master_subnet
        security_groups_ids = []
        if vpc_security_group:
            security_groups_ids.append(vpc_security_group)

        # Initialize CpuOptions
        disable_hyperthreading = cluster_section.get_param_value("disable_hyperthreading")
        master_vcpus = get_instance_vcpus(master_instance_type)
        master_threads_per_core = get_default_threads_per_core(master_instance_type)
        compute_vcpus = get_instance_vcpus(compute_instance_type)
        compute_threads_per_core = get_default_threads_per_core(compute_instance_type)
        master_cpu_options = (
            {"CoreCount": master_vcpus // master_threads_per_core, "ThreadsPerCore": 1}
            if disable_hyperthreading and disable_ht_via_cpu_options(master_instance_type, master_threads_per_core)
            else {}
        )
        compute_cpu_options = (
            {"CoreCount": compute_vcpus // compute_threads_per_core, "ThreadsPerCore": 1}
            if disable_hyperthreading and disable_ht_via_cpu_options(compute_instance_type, compute_threads_per_core)
            else {}
        )

        # Initialize Placement Group Logic
        placement_group = cluster_section.get_param_value("placement_group")
        placement = cluster_section.get_param_value("placement")
        master_placement_group = (
            {"GroupName": placement_group}
            if placement_group not in [None, "NONE", "DYNAMIC"] and placement == "cluster"
            else {}
        )
        compute_placement_group = (
            {"GroupName": placement_group} if placement_group not in [None, "NONE", "DYNAMIC"] else {}
        )

        try:
            latest_alinux_ami_id = self._get_latest_alinux_ami_id()

            # Test Master Instance Configuration
            self._ec2_run_instance(
                pcluster_config,
                InstanceType=master_instance_type,
                MinCount=1,
                MaxCount=1,
                ImageId=latest_alinux_ami_id,
                SubnetId=master_subnet,
                SecurityGroupIds=security_groups_ids,
                CpuOptions=master_cpu_options,
                Placement=master_placement_group,
                DryRun=True,
            )

            # Test Compute Instances Configuration
            self._ec2_run_instance(
                pcluster_config,
                InstanceType=compute_instance_type,
                MinCount=1,
                MaxCount=1,
                ImageId=latest_alinux_ami_id,
                SubnetId=compute_subnet,
                SecurityGroupIds=security_groups_ids,
                CpuOptions=compute_cpu_options,
                Placement=compute_placement_group,
                DryRun=True,
            )
        except ClientError:
            pcluster_config.error("Unable to validate configuration parameters.")
