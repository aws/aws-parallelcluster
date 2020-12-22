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


class HITClusterModel(ClusterModel):
    """HIT (Heterogeneous Instance Type model) cluster model."""

    def __init__(self):
        super(HITClusterModel, self).__init__("HIT")

    def get_cluster_section_definition(self):
        """Get the cluster section definition used by the cluster model."""
        return mappings.CLUSTER_HIT

    def get_start_command(self, pcluster_config):
        """Get the start command for the HIT cluster."""
        from pcluster.cli_commands.start import HITStartCommand

        return HITStartCommand()

    def get_stop_command(self, pcluster_config):
        """Get the stop command for the HIT cluster."""
        from pcluster.cli_commands.stop import HITStopCommand

        return HITStopCommand()

    def test_configuration(self, pcluster_config):
        """Try to launch the requested instances (in dry-run mode) to verify configuration parameters."""
        cluster_section = pcluster_config.get_section("cluster")
        vpc_section = pcluster_config.get_section("vpc")

        if cluster_section.get_param_value("scheduler") == "awsbatch":
            return

        head_node_instance_type = cluster_section.get_param_value("master_instance_type")

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

        # Set vcpus according to queue's disable_hyperthreading and instance features
        head_node_vcpus = head_node_instance_type_info.vcpus_count()

        head_node_threads_per_core = head_node_instance_type_info.default_threads_per_core()
        head_node_cpu_options = (
            {"CoreCount": head_node_vcpus // head_node_threads_per_core, "ThreadsPerCore": 1}
            if disable_hyperthreading
            and disable_ht_via_cpu_options(head_node_instance_type, head_node_threads_per_core)
            else {}
        )
        try:
            latest_alinux_ami_id = self._get_latest_alinux_ami_id()

            head_node_network_interfaces = self.build_launch_network_interfaces(
                network_interfaces_count=int(cluster_section.get_param_value("network_interfaces_count")[0]),
                use_efa=False,  # EFA is not supported on head node
                security_group_ids=security_groups_ids,
                subnet=head_node_subnet,
                use_public_ips=vpc_section.get_param_value("use_public_ips"),
            )

            # Test Head Node Instance Configuration
            self._ec2_run_instance(
                pcluster_config,
                InstanceType=head_node_instance_type,
                MinCount=1,
                MaxCount=1,
                ImageId=latest_alinux_ami_id,
                CpuOptions=head_node_cpu_options,
                NetworkInterfaces=head_node_network_interfaces,
                DryRun=True,
            )

            for _, queue_section in pcluster_config.get_sections("queue").items():
                queue_placement_group = queue_section.get_param_value("placement_group")
                queue_placement_group = (
                    {"GroupName": queue_placement_group}
                    if queue_placement_group not in [None, "NONE", "DYNAMIC"]
                    else {}
                )

                compute_resource_section = self.select_dryrun_compute_resource(queue_section, pcluster_config)

                disable_hyperthreading = compute_resource_section.get_param_value(
                    "disable_hyperthreading"
                ) and compute_resource_section.get_param_value("disable_hyperthreading_via_cpu_options")
                self.__test_compute_resource(
                    pcluster_config,
                    compute_resource_section,
                    disable_hyperthreading=disable_hyperthreading,
                    ami_id=latest_alinux_ami_id,
                    subnet=compute_subnet,
                    security_groups_ids=security_groups_ids,
                    placement_group=queue_placement_group,
                )

        except ClientError:
            pcluster_config.error("Unable to validate configuration parameters.")

    def select_dryrun_compute_resource(self, queue_section, pcluster_config):
        """
        Select the "best" compute resource to run dryrun tests against.

        Resources with multiple NICs are preferred among others.
        """
        # Temporarily limiting dryrun tests to 1 per queue to save boto3 calls.
        compute_resource_labels = queue_section.get_param("compute_resource_settings").referred_section_labels
        dryrun_section = pcluster_config.get_section("compute_resource", compute_resource_labels[0])
        for section_label in compute_resource_labels:
            compute_resource_section = pcluster_config.get_section("compute_resource", section_label)
            if compute_resource_section.get_param_value("network_interfaces") > 1:
                dryrun_section = compute_resource_section
                break

        return dryrun_section

    def __test_compute_resource(
        self,
        pcluster_config,
        compute_resource_section,
        disable_hyperthreading=None,
        ami_id=None,
        subnet=None,
        security_groups_ids=None,
        placement_group=None,
    ):
        """Test Compute Resource Instance Configuration."""
        vcpus = compute_resource_section.get_param_value("vcpus")
        compute_cpu_options = {"CoreCount": vcpus, "ThreadsPerCore": 1} if disable_hyperthreading else {}
        network_interfaces_count = compute_resource_section.get_param_value("network_interfaces")
        use_public_ips = self.public_ips_in_compute_subnet(pcluster_config, network_interfaces_count)

        network_interfaces = self.build_launch_network_interfaces(
            network_interfaces_count,
            compute_resource_section.get_param_value("enable_efa"),
            security_groups_ids,
            subnet,
            use_public_ips,
        )

        self._ec2_run_instance(
            pcluster_config,
            InstanceType=compute_resource_section.get_param_value("instance_type"),
            MinCount=1,
            MaxCount=1,
            ImageId=ami_id,
            CpuOptions=compute_cpu_options,
            Placement=placement_group,
            NetworkInterfaces=network_interfaces,
            DryRun=True,
        )
