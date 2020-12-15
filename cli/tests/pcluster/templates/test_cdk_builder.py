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

import os

import yaml
from aws_cdk import core

from common.utils import load_yaml
from pcluster.cluster import HeadNode, SlurmCluster
from pcluster.config.cluster_config import (
    ClusterConfig,
    ComputeResourceConfig,
    HeadNodeConfig,
    HeadNodeNetworkingConfig,
    ImageConfig,
    QueueConfig,
    QueueNetworkingConfig,
    SchedulingConfig,
    SshConfig,
)
from pcluster.templates.cdk_builder import CDKTemplateBuilder, HeadNodeConstruct


def dummy_head_node_config():
    """Generate dummy head node configuration."""
    image_config = ImageConfig(os="fakeos")
    head_node_networking_config = HeadNodeNetworkingConfig(subnet_id="test")
    ssh_config = SshConfig(key_name="test")
    return HeadNodeConfig(
        instance_type="fake",
        networking_config=head_node_networking_config,
        ssh_config=ssh_config,
        image_config=image_config,
    )


def dummy_cluster_config():
    """Generate dummy cluster configuration."""
    image_config = ImageConfig(os="fakeos")
    head_node_config = dummy_head_node_config()
    compute_resources_config = [ComputeResourceConfig(instance_type="test")]
    queue_networking_config = QueueNetworkingConfig(subnet_ids=["test"])
    queues_config = [
        QueueConfig(
            name="test", networking_config=queue_networking_config, compute_resources_config=compute_resources_config
        )
    ]
    scheduling_config = SchedulingConfig(scheduler="test", queues_config=queues_config)
    return ClusterConfig(
        image_config=image_config, head_node_config=head_node_config, scheduling_config=scheduling_config
    )


def test_cluster_builder():
    slurm_cluster = SlurmCluster(region="eu-west-1", name="test", config=dummy_cluster_config())
    generated_template = CDKTemplateBuilder().build(cluster=slurm_cluster)
    print(yaml.dump(generated_template))
    # TODO assert content of the template by matching expected template


def test_head_node_construct(tmpdir):

    head_node = HeadNode(config=dummy_head_node_config())

    class DummyStack(core.Stack):
        """Simple Stack to test a specific construct."""

        def __init__(self, scope: core.Construct, construct_id: str, head_node: HeadNode, **kwargs) -> None:
            super().__init__(scope, construct_id, **kwargs)

            HeadNodeConstruct(self, "HeadNode", head_node)

    output_file = "cluster"
    app = core.App(outdir=str(tmpdir))
    DummyStack(app, output_file, head_node=head_node)
    app.synth()
    generated_template = load_yaml(os.path.join(tmpdir, f"{output_file}.template.json"))

    print(yaml.dump(generated_template))
    # TODO assert content of the template by matching expected template
