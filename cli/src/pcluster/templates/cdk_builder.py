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

import logging
import os
import tempfile

from pcluster.config.cluster_config import BaseClusterConfig
from pcluster.config.imagebuilder_config import ImageBuilderConfig
from pcluster.models.s3_bucket import S3Bucket
from pcluster.utils import load_yaml_dict

LOGGER = logging.getLogger(__name__)


class CDKTemplateBuilder:
    """Create the template, starting from the given resources."""

    @staticmethod
    def build_cluster_template(
        cluster_config: BaseClusterConfig, bucket: S3Bucket, stack_name: str, log_group_name: str = None
    ):
        """Build template for the given cluster and return as output in Yaml format."""
        LOGGER.info("Importing CDK...")
        from aws_cdk.core import App  # pylint: disable=C0415

        from pcluster.templates.cluster_stack import ClusterCdkStack  # pylint: disable=C0415

        LOGGER.info("CDK import completed successfully")
        LOGGER.info("Starting CDK template generation...")
        with tempfile.TemporaryDirectory() as tempdir:
            output_file = str(stack_name)
            app = App(outdir=str(tempdir))
            ClusterCdkStack(app, output_file, stack_name, cluster_config, bucket, log_group_name)
            app.synth()
            generated_template = load_yaml_dict(os.path.join(tempdir, f"{output_file}.template.json"))
        LOGGER.info("CDK template generation completed successfully")

        return generated_template

    @staticmethod
    def build_imagebuilder_template(image_config: ImageBuilderConfig, image_id: str, bucket: S3Bucket):
        """Build template for the given imagebuilder and return as output in Yaml format."""
        from aws_cdk.core import App  # pylint: disable=C0415

        from pcluster.templates.imagebuilder_stack import ImageBuilderCdkStack  # pylint: disable=C0415

        with tempfile.TemporaryDirectory() as tempdir:
            output_file = "imagebuilder"
            app = App(outdir=str(tempdir))
            ImageBuilderCdkStack(app, output_file, image_config, image_id, bucket)
            app.synth()
            generated_template = load_yaml_dict(os.path.join(tempdir, f"{output_file}.template.json"))

        return generated_template
