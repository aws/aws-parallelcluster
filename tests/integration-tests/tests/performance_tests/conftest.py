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

import boto3
import pytest

OSS_REQUIRING_EXTRA_DEPS = ["alinux2023", "rhel8", "rocky8"]
NUMBER_OF_NODES = [8, 16, 32]


@pytest.fixture(scope="session")
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
