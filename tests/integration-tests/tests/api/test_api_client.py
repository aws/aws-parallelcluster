# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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


import base64

import boto3
import pytest
from assertpy import assert_that
from botocore.config import Config
from pcluster_client.api import cluster_operations_api
from pcluster_client.model.create_cluster_request_content import CreateClusterRequestContent
from utils import generate_stack_name


def _cloudformation_wait(region, stack_name, status):
    config = Config(region_name=region)
    cloud_formation = boto3.client("cloudformation", config=config)
    waiter = cloud_formation.get_waiter(status)
    waiter.wait(StackName=stack_name)


@pytest.mark.usefixtures("region", "os", "instance")
def test_cluster_operations(request, scheduler, region, pcluster_config_reader, clusters_factory, api_client):
    cluster_config_path = pcluster_config_reader(scaledown_idletime=3)

    with open(cluster_config_path) as config_file:
        cluster_config = config_file.read()

    stack_name = generate_stack_name("integ-tests", request.config.getoption("stackname_suffix"))
    client = cluster_operations_api.ClusterOperationsApi(api_client)
    resp = _test_create(client, cluster_config, region, stack_name)
    cluster = resp["cluster"]
    cluster_name = cluster["cluster_name"]
    assert_that(cluster_name).is_equal_to(stack_name)

    _cloudformation_wait(region, stack_name, "stack_create_complete")

    _test_list_clusters(client, cluster, region)
    _test_describe_cluster(client, cluster, region)
    _test_delete_cluster(client, cluster, region)


def _test_list_clusters(client, cluster, region):
    response = client.list_clusters(region=region)
    cluster_names = [c["cluster_name"] for c in response["items"]]
    cluster_name = cluster["cluster_name"]
    assert_that(cluster_names).contains(cluster_name)


def _test_describe_cluster(client, cluster, region):
    cluster_name = cluster["cluster_name"]
    response = client.describe_cluster(cluster_name, region=region)
    assert_that(response.cluster_name).is_equal_to(cluster_name)


def _test_create(client, cluster_config, region, stack_name):
    cluster_config_data = base64.b64encode(cluster_config.encode("utf-8")).decode("utf-8")
    body = CreateClusterRequestContent(stack_name, cluster_config_data, region=region)
    return client.create_cluster(body)


def _test_delete_cluster(client, cluster, region):
    cluster_name = cluster["cluster_name"]
    client.delete_cluster(cluster_name, region=region)

    _cloudformation_wait(region, cluster_name, "stack_delete_complete")

    response = client.list_clusters(region=region)
    cluster_names = [c["cluster_name"] for c in response["items"]]
    assert_that(cluster_names).does_not_contain(cluster_name)
