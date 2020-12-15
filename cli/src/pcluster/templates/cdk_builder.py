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

import os
import tempfile

from aws_cdk import aws_ec2 as ec2
from aws_cdk import core

from common.utils import load_yaml
from pcluster.cluster import Cluster, Fsx, HeadNode


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
        proxy_server = "proxy_server"
        placement_group = "placement_group"
        update_waiter_function_arn = "update_waiter_function_arn"
        use_master_public_ip = True
        master_network_interfaces_count = 5
        master_eni = "master_eni"
        master_security_groups = ["master_security_groups"]
        master_subnet_id = "master_subnet_id"
        image_id = "image_id"
        iam_instance_profile = "iam_instance_profile"

        # Conditions
        master_core_info = master_core_count.split(",")
        disable_master_hyperthreading = master_core_info[0] != -1 and master_core_info[0] != "NONE"
        disable_compute_hyperthreading = master_core_info != -1 and master_core_info != "NONE"
        disable_hyperthreading_via_cpu_options = disable_master_hyperthreading and master_core_info[1] == "true"
        disable_hyperthreading_manually = disable_master_hyperthreading and not disable_hyperthreading_via_cpu_options
        is_master_instance_ebs_opt = master_instance_type not in [
            "cc2.8xlarge",
            "cr1.8xlarge",
            "m3.medium",
            "m3.large",
            "c3.8xlarge",
            "c3.large",
            "",
        ]
        use_proxy = proxy_server != "NONE"
        use_placement_group = placement_group != "NONE"
        has_update_waiter_function = update_waiter_function_arn != "NONE"
        has_master_public_ip = use_master_public_ip == "true"
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


class FsxConstruct(core.Construct):
    """Create the resources related to the FSX."""

    # https://cdkworkshop.com/30-python/40-hit-counter/100-api.html
    def __init__(self, scope: core.Construct, id: str, fsx: Fsx, **kwargs):
        super().__init__(scope, id)
        self.fsx = fsx
        # TODO add all the other required info other than fsx object and generate template
        # TODO Verify if there are building blocks ready to be used


class ClusterStack(core.Stack):
    """Create the Stack and delegate to specific Construct for the creation of all the resources for the Cluster."""

    def __init__(self, scope: core.Construct, construct_id: str, cluster: Cluster, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self._cluster = cluster

        HeadNodeConstruct(self, "HeadNode", cluster.head_node)
        if cluster.fsx:
            FsxConstruct(self, "Fsx", cluster.fsx)
        # if cluster.efs:
        #    EfsConstruct(cluster.efs)  # TODO Verify if there are building blocks ready to be used
        # for ebs in cluster.ebs_volumes:
        #    EbsConstruct(ebs)  # Verify if there are building blocks ready to be used


class CDKTemplateBuilder:
    """Create the resources related to the HeadNode."""

    def build(self, cluster: Cluster):
        """Build template for the given cluster and return as output in Yaml format."""

        with tempfile.TemporaryDirectory() as tempdir:
            output_file = "cluster"
            app = core.App(outdir=str(tempdir))
            ClusterStack(app, output_file, cluster=cluster)
            app.synth()
            generated_template = load_yaml(os.path.join(tempdir, f"{output_file}.template.json"))

        return generated_template
