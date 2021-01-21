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

from aws_cdk import core

from common.utils import load_yaml
from pcluster.models.cluster import Cluster
from pcluster.templates.cluster_stack import ClusterStack


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
