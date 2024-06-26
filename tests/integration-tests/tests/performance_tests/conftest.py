# Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.

import logging
import os

import boto3
import pytest
from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

from conftest import _get_default_template_values, inject_additional_config_settings, \
    inject_additional_image_configs_settings

OSS_REQUIRING_EXTRA_DEPS = ["alinux2023", "rhel8", "rocky8"]
NUMBER_OF_NODES = [8, 16, 32]


@pytest.fixture(scope="class")
def shared_performance_test_cluster(
    vpc_stack, pcluster_config_reader, clusters_factory, test_datadir, s3_bucket_factory
):

    def _shared_performance_test_cluster(instance, os, region, scheduler):
        bucket_name = s3_bucket_factory()
        s3 = boto3.client("s3")
        s3.upload_file(str(test_datadir / "dependencies.install.sh"), bucket_name, "scripts/dependencies.install.sh")

        cluster_config = pcluster_config_reader(
            bucket_name=bucket_name,
            install_extra_deps=os in OSS_REQUIRING_EXTRA_DEPS,
            number_of_nodes=max(NUMBER_OF_NODES),
        )
        cluster = clusters_factory(cluster_config)
        logging.info("Cluster Created")
        return cluster

    return _shared_performance_test_cluster


@pytest.fixture(scope="class")
def shared_test_datadir(request, datadir):
    """
    Inject the datadir with resources for the specific test function.

    If the test function is declared in a class then datadir is ClassName/FunctionName
    otherwise it is only FunctionName.
    """
    function_name = request.function.__name__
    if not request.cls:
        return datadir / function_name

    class_name = request.cls.__name__
    return datadir / "{0}/{1}".format(class_name, function_name)


@pytest.fixture(scope="class")
def shared_pcluster_config_reader(test_datadir, vpc_stack, request, region):
    """
    Define a fixture to render pcluster config templates associated to the running test.

    The config for a given test is a pcluster.config.yaml file stored in the configs_datadir folder.
    The config can be written by using Jinja2 template engine.
    The current renderer already replaces placeholders for current keys:
        {{ region }}, {{ os }}, {{ instance }}, {{ scheduler}}, {{ key_name }},
        {{ vpc_id }}, {{ public_subnet_id }}, {{ private_subnet_id }}, {{ default_vpc_security_group_id }}
    The current renderer injects options for custom templates and packages in case these
    are passed to the cli and not present already in the cluster config.
    Also sanity_check is set to true by default unless explicitly set in config.

    :return: a _config_renderer(**kwargs) function which gets as input a dictionary of values to replace in the template
    """

    def _config_renderer(config_file="pcluster.config.yaml", benchmarks=None, output_file=None, **kwargs):
        config_file_path = test_datadir / config_file
        if not os.path.isfile(config_file_path):
            raise FileNotFoundError(f"Cluster config file not found in the expected dir {config_file_path}")
        output_file_path = test_datadir / output_file if output_file else config_file_path
        default_values = _get_default_template_values(vpc_stack, request)
        file_loader = FileSystemLoader(str(test_datadir))
        env = SandboxedEnvironment(loader=file_loader)
        rendered_template = env.get_template(config_file).render(**{**default_values, **kwargs})
        output_file_path.write_text(rendered_template)
        if not config_file.endswith("image.config.yaml"):
            inject_additional_config_settings(output_file_path, request, region, benchmarks)
        else:
            inject_additional_image_configs_settings(output_file_path, request)
        return output_file_path

    return _config_renderer
