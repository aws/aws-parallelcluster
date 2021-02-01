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

from common.utils import load_yaml_dict
from pcluster.models.cluster import HeadNode
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.templates.cluster_stack import HeadNodeConstruct
from tests.pcluster.models.cluster_dummy_model import dummy_cluster, dummy_head_node


def test_cluster_builder():
    generated_template = CDKTemplateBuilder().build(cluster=dummy_cluster())
    print(yaml.dump(generated_template))
    # TODO assert content of the template by matching expected template


def test_head_node_construct(tmpdir):
    # TODO verify if it's really useful

    class DummyStack(core.Stack):
        """Simple Stack to test a specific construct."""

        def __init__(self, scope: core.Construct, construct_id: str, head_node: HeadNode, **kwargs) -> None:
            super().__init__(scope, construct_id, **kwargs)

            HeadNodeConstruct(self, "HeadNode", head_node)

    output_file = "cluster"
    app = core.App(outdir=str(tmpdir))
    DummyStack(app, output_file, head_node=dummy_head_node())
    app.synth()
    generated_template = load_yaml_dict(os.path.join(tmpdir, f"{output_file}.template.json"))

    print(yaml.dump(generated_template))
    # TODO assert content of the template by matching expected template
