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

from aws_cdk.core import App

from common.utils import load_yaml_dict
from pcluster.models.cluster_config import BaseClusterConfig
from pcluster.models.common import S3Bucket
from pcluster.models.imagebuilder_config import ImageBuilderConfig
from pcluster.templates.cluster_stack import ClusterCdkStack
from pcluster.templates.imagebuilder_stack import ImageBuilderCdkStack


class CDKTemplateBuilder:
    """Create the template, starting from the given resources."""

    @staticmethod
    def build_cluster_template(cluster_config: BaseClusterConfig, bucket: S3Bucket, stack_name: str):
        """Build template for the given cluster and return as output in Yaml format."""
        with tempfile.TemporaryDirectory() as tempdir:
            output_file = str(stack_name)
            app = App(outdir=str(tempdir))
            ClusterCdkStack(app, output_file, stack_name, cluster_config, bucket)
            app.synth()
            generated_template = load_yaml_dict(os.path.join(tempdir, f"{output_file}.template.json"))

        return generated_template

    @staticmethod
    def build_imagebuilder_template(image_config: ImageBuilderConfig, image_name: str, bucket: S3Bucket):
        """Build template for the given imagebuilder and return as output in Yaml format."""
        with tempfile.TemporaryDirectory() as tempdir:
            output_file = "imagebuilder"
            app = App(outdir=str(tempdir))
            ImageBuilderCdkStack(app, output_file, image_config, image_name, bucket)
            app.synth()
            generated_template = load_yaml_dict(os.path.join(tempdir, f"{output_file}.template.json"))

        return generated_template
