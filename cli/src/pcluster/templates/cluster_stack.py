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

#
# This module contains all the classes required to convert a Cluster into a CFN template by using CDK.
#

from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_efs as efs
from aws_cdk import aws_fsx as fsx
from aws_cdk import core

from common.aws.aws_api import AWSApi
from pcluster.models.cluster import HeadNode, SharedEbs, SharedEfs, SharedFsx, SharedStorage
from pcluster.models.cluster_slurm import SlurmCluster


class HeadNodeConstruct(core.Construct):
    """Create the resources related to the HeadNode."""

    # https://cdkworkshop.com/30-python/40-hit-counter/100-api.html
    def __init__(self, scope: core.Construct, id: str, head_node: HeadNode, **kwargs):
        super().__init__(scope, id)
        self.head_node = head_node

        # TODO: use attributes from head_node instead of using these static variables.
        master_instance_type = self.head_node.instance_type
        master_core_count = "-1,true"
        # compute_core_count = "-1"
        key_name = "keyname"
        root_device = "root_device"
        root_volume_size = 10
        main_stack_name = "main_stack_name"
        # proxy_server = "proxy_server"
        placement_group = "placement_group"
        # update_waiter_function_arn = "update_waiter_function_arn"
        # use_master_public_ip = True
        master_network_interfaces_count = 5
        master_eni = "master_eni"
        master_security_groups = ["master_security_groups"]
        master_subnet_id = "master_subnet_id"
        image_id = "image_id"
        iam_instance_profile = "iam_instance_profile"

        # Conditions
        master_core_info = master_core_count.split(",")
        disable_master_hyperthreading = master_core_info[0] != -1 and master_core_info[0] != "NONE"
        # disable_compute_hyperthreading = master_core_info != -1 and master_core_info != "NONE"
        disable_hyperthreading_via_cpu_options = disable_master_hyperthreading and master_core_info[1] == "true"
        # disable_hyperthreading_manually = disable_master_hyperthreading and not disable_hyperthreading_via_cpu_options
        is_master_instance_ebs_opt = master_instance_type not in [
            "cc2.8xlarge",
            "cr1.8xlarge",
            "m3.medium",
            "m3.large",
            "c3.8xlarge",
            "c3.large",
            "",
        ]
        # use_proxy = proxy_server != "NONE"
        use_placement_group = placement_group != "NONE"
        # has_update_waiter_function = update_waiter_function_arn != "NONE"
        # has_master_public_ip = use_master_public_ip == "true"
        # use_nic1 = master_network_interfaces_count ... TODO

        cpu_options = ec2.CfnLaunchTemplate.CpuOptionsProperty(
            core_count=int(master_core_info[0]),
            threads_per_core=1,
        )
        block_device_mappings = []
        for _, (device_name_index, virtual_name_index) in enumerate(zip(list(map(chr, range(97, 121))), range(0, 24))):
            device_name = "/dev/xvdb{0}".format(device_name_index)
            virtual_name = "ephemeral{0}".format(virtual_name_index)
            block_device_mappings.append(
                ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(device_name=device_name, virtual_name=virtual_name)
            )

        block_device_mappings.append(
            ec2.CfnLaunchTemplate.BlockDeviceMappingProperty(
                device_name=root_device,
                ebs=ec2.CfnLaunchTemplate.EbsProperty(
                    volume_size=root_volume_size,
                    volume_type="gp2",
                ),
            )
        )

        tags_raw = [
            ("Application", main_stack_name),
            ("Name", "Master"),
            ("aws-parallelcluster-node-type", "Master"),
            ("ClusterName", "parallelcluster-{0}".format(main_stack_name)),
            # ... TODO
        ]
        tags = []
        for key, value in tags_raw:
            tags.append(core.CfnTag(key=key, value=value))
        tag_specifications = [
            ec2.CfnLaunchTemplate.TagSpecificationProperty(resource_type="instance", tags=tags),
            ec2.CfnLaunchTemplate.TagSpecificationProperty(resource_type="volume", tags=tags),  # FIXME
        ]

        network_interfaces = [
            ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                network_interface_id=master_eni,
                device_index=0,
            )
        ]
        for index in range(1, master_network_interfaces_count + 1):
            network_interfaces.append(
                ec2.CfnLaunchTemplate.NetworkInterfaceProperty(
                    device_index=index,
                    network_card_index=index,
                    groups=master_security_groups,
                    subnet_id=master_subnet_id,
                )
            )

        launch_template_data = ec2.CfnLaunchTemplate.LaunchTemplateDataProperty(
            instance_type=master_instance_type,
            cpu_options=cpu_options if disable_hyperthreading_via_cpu_options else None,
            block_device_mappings=block_device_mappings,
            key_name=key_name,
            tag_specifications=tag_specifications,
            network_interfaces=network_interfaces,
            image_id=image_id,
            ebs_optimized=is_master_instance_ebs_opt,
            iam_instance_profile=ec2.CfnLaunchTemplate.IamInstanceProfileProperty(name=iam_instance_profile),
            placement=ec2.CfnLaunchTemplate.PlacementProperty(
                group_name=placement_group if use_placement_group else None
            ),
            # user_data= TODO
            # https://stackoverflow.com/questions/57753032/how-to-obtain-pseudo-parameters-user-data-with-aws-cdk
        )

        launch_template = ec2.CfnLaunchTemplate(
            self, id="MasterServerLaunchTemplate", launch_template_data=launch_template_data
        )

        master_instance = ec2.CfnInstance(
            self,
            id="MasterServer",
            launch_template=ec2.CfnInstance.LaunchTemplateSpecificationProperty(
                launch_template_id=launch_template.ref, version=launch_template.attr_latest_version_number
            ),
        )

        core.CfnOutput(
            self,
            id="privateip",
            description="Private IP Address of the Master host",
            value=master_instance.attr_public_ip,
        )
        core.CfnOutput(
            self,
            id="publicip",
            description="Public IP Address of the Master host",
            value=master_instance.attr_public_ip,
        )
        core.CfnOutput(
            self,
            id="dnsname",
            description="Private DNS name of the Master host",
            value=master_instance.attr_private_dns_name,
        )

        # TODO metadata?

        # https://docs.aws.amazon.com/cdk/latest/guide/use_cfn_template.html
        # with open('master-server-substack.cfn.yaml', 'r') as f:
        # template = yaml.load(f, Loader=yaml.SafeLoader)
        # include = core.CfnInclude(self, 'ExistingInfrastructure',
        #    template=template,
        # )


class ClusterStack(core.Stack):
    """Create the Stack and delegate to specific Construct for the creation of all the resources for the Cluster."""

    def __init__(self, scope: core.Construct, construct_id: str, cluster: SlurmCluster, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self._cluster = cluster

        # Storage filesystem Ids
        self._storage_resource_ids = {storage_type: [] for storage_type in SharedStorage.Type}

        # Compute security group Ids
        # TODO: add sgs created from main stack
        self._compute_security_groups = []
        self._compute_security_groups.extend(self._cluster.compute_security_groups)

        HeadNodeConstruct(self, "HeadNode", cluster.head_node)

        if cluster.shared_storage:
            for storage in cluster.shared_storage:
                self._add_shared_storage(storage)

        self._add_shared_storage_outputs()

    def _add_shared_storage(self, storage: SharedStorage):
        """Add specific Cfn Resources to map the shared storage and store the output filesystem id."""
        storage_id = None
        cfn_resource_id = "{0}{1}".format(
            storage.shared_storage_type.name, len(self._storage_resource_ids[storage.shared_storage_type])
        )
        if storage.shared_storage_type == SharedStorage.Type.FSX:
            storage_id = self._add_fsx_storage(cfn_resource_id, storage)
        elif storage.shared_storage_type == SharedStorage.Type.EBS:
            storage_id = self._add_ebs_volume(cfn_resource_id, storage)
        elif storage.shared_storage_type == SharedStorage.Type.EFS:
            storage_id = self._add_efs_storage(cfn_resource_id, storage)

        # Store filesystem id
        storage_ids_list = self._storage_resource_ids[storage.shared_storage_type]
        if not storage_ids_list:
            storage_ids_list = []
            self._storage_resource_ids[storage.shared_storage_type] = storage_ids_list
        storage_ids_list.append(storage_id)

    def _add_shared_storage_outputs(self):
        """Add the ids of the managed filesystem to the Stack Outputs."""
        for storage_type, storage_ids in self._storage_resource_ids.items():
            core.CfnOutput(
                scope=self,
                id="{0}Ids".format(storage_type.name),
                description="{0} Filesystem IDs".format(storage_type.name),
                value=",".join(storage_ids),
            )

    def _add_fsx_storage(self, id: str, shared_fsx: SharedFsx):
        """Add specific Cfn Resources to map the FSX storage."""
        fsx_id = shared_fsx.file_system_id

        if not fsx_id and shared_fsx.mount_dir:
            fsx_resource = fsx.CfnFileSystem(
                scope=self,
                storage_capacity=shared_fsx.storage_capacity,
                lustre_configuration=fsx.CfnFileSystem.LustreConfigurationProperty(
                    deployment_type=shared_fsx.deployment_type,
                    imported_file_chunk_size=shared_fsx.imported_file_chunk_size,
                    export_path=shared_fsx.export_path,
                    import_path=shared_fsx.import_path,
                    weekly_maintenance_start_time=shared_fsx.weekly_maintenance_start_time,
                    automatic_backup_retention_days=shared_fsx.automatic_backup_retention_days,
                    copy_tags_to_backups=shared_fsx.copy_tags_to_backups,
                    daily_automatic_backup_start_time=shared_fsx.daily_automatic_backup_start_time,
                    per_unit_storage_throughput=shared_fsx.per_unit_storage_throughput,
                    auto_import_policy=shared_fsx.auto_import_policy,
                    drive_cache_type=shared_fsx.drive_cache_type,
                ),
                backup_id=shared_fsx.backup_id,
                kms_key_id=shared_fsx.kms_key_id,
                id=id,
                file_system_type="LUSTRE",
                storage_type=shared_fsx.drive_cache_type,
                subnet_ids=self._cluster.compute_subnet_ids,
                security_group_ids=self._cluster.compute_security_groups,
            )
            fsx_id = fsx_resource.ref

        return fsx_id

    def _add_efs_storage(self, id: str, shared_efs: SharedEfs):
        """Add specific Cfn Resources to map the EFS storage."""
        # EFS FileSystem
        efs_id = shared_efs.file_system_id
        if not efs_id and shared_efs.mount_dir:
            efs_resource = efs.CfnFileSystem(
                scope=self,
                id=id,
                encrypted=shared_efs.encrypted,
                kms_key_id=shared_efs.kms_key_id,
                performance_mode=shared_efs.performance_mode,
                provisioned_throughput_in_mibps=shared_efs.provisioned_throughput,
                throughput_mode=shared_efs.throughput_mode,
            )
            efs_id = efs_resource.ref

        checked_availability_zones = []
        # Mount Targets for Compute Fleet
        compute_subnet_ids = self._cluster.compute_subnet_ids
        for subnet_id in compute_subnet_ids:
            self._add_efs_mount_target(
                id, efs_id, self._cluster.compute_security_groups, subnet_id, checked_availability_zones
            )

        # Mount Target for Head Node
        self._add_efs_mount_target(
            id,
            efs_id,
            self._cluster.head_node.networking.security_groups,
            self._cluster.head_node.networking.subnet_id,
            checked_availability_zones,
        )
        return efs_id

    def _add_efs_mount_target(
        self, efs_cfn_resource_id, file_system_id, security_groups, subnet_id, checked_availability_zones
    ):
        """Create a EFS Mount Point for the file system, if not already available on the same AZ."""
        availability_zone = AWSApi.instance().ec2.get_availability_zone_of_subnet(subnet_id)
        if availability_zone not in checked_availability_zones:
            mount_target_id = AWSApi.instance().efs.get_efs_mount_target_id(file_system_id, availability_zone)

            if not mount_target_id:
                efs.CfnMountTarget(
                    scope=self,
                    id="{0}MT{1}".format(efs_cfn_resource_id, availability_zone),
                    file_system_id=file_system_id,
                    security_groups=security_groups,
                    subnet_id=subnet_id,
                )
            checked_availability_zones.append(availability_zone)

    def _add_ebs_volume(self, id: str, shared_ebs: SharedEbs):
        """Add specific Cfn Resources to map the EBS storage."""
        ebs_id = shared_ebs.volume_id
        if not ebs_id and shared_ebs.mount_dir:
            ebs_resource = ec2.CfnVolume(
                scope=self,
                id=id,
                availability_zone=AWSApi.instance().ec2.get_availability_zone_of_subnet(
                    self._cluster.head_node.networking.subnet_id
                ),
                encrypted=shared_ebs.encrypted,
                iops=shared_ebs.iops,
                throughput=shared_ebs.throughput,
                kms_key_id=shared_ebs.kms_key_id,
                size=shared_ebs.size,
                snapshot_id=shared_ebs.snapshot_id,
                volume_type=shared_ebs.volume_type,
            )
            ebs_id = ebs_resource.ref

        return ebs_id
