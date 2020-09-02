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
from pcluster.utils import disable_ht_via_cpu_options, get_default_threads_per_core, get_instance_type


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

        if not cluster_section or cluster_section.get_param_value("scheduler") == "awsbatch" or not vpc_section:
            return

        master_instance_type = cluster_section.get_param_value("master_instance_type")

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
        master_instance_type_info = get_instance_type(master_instance_type)

        # Set vcpus according to queue's disable_hyperthreading and instance features
        vcpus_info = master_instance_type_info.get("VCpuInfo")
        master_vcpus = vcpus_info.get("DefaultVCpus")

        master_cpu_options = {"CoreCount": master_vcpus // 2, "ThreadsPerCore": 1} if disable_hyperthreading else {}
        master_threads_per_core = get_default_threads_per_core(master_instance_type)
        master_cpu_options = (
            {"CoreCount": master_vcpus // master_threads_per_core, "ThreadsPerCore": 1}
            if disable_hyperthreading and disable_ht_via_cpu_options(master_instance_type, master_threads_per_core)
            else {}
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
                DryRun=True,
            )

            for _, queue_section in pcluster_config.get_sections("queue").items():
                queue_placement_group = queue_section.get_param_value("placement_group")
                queue_placement_group = (
                    {"GroupName": queue_placement_group}
                    if queue_placement_group not in [None, "NONE", "DYNAMIC"]
                    else {}
                )

                compute_resource_settings = queue_section.get_param_value("compute_resource_settings")

                # Temporarily limiting dryrun tests to 1 per queue to save boto3 calls.
                compute_resource_section = pcluster_config.get_section(
                    "compute_resource", compute_resource_settings.split(",")[0]
                )

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

        self._ec2_run_instance(
            pcluster_config,
            InstanceType=compute_resource_section.get_param_value("instance_type"),
            MinCount=1,
            MaxCount=1,
            ImageId=ami_id,
            SubnetId=subnet,
            SecurityGroupIds=security_groups_ids,
            CpuOptions=compute_cpu_options,
            Placement=placement_group,
            DryRun=True,
        )
