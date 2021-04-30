#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import json

from assertpy import assert_that

from pcluster.api.models.cluster_status import ClusterStatus
from pcluster.api.models.validation_level import ValidationLevel


class TestCreateCluster:
    def test_create_cluster(self, client):
        create_cluster_request_content = {
            "name": "clustername",
            "region": "eu-west-1",
            "clusterConfiguration": "clusterConfiguration",
        }
        query_string = [
            ("suppressValidators", ["suppress_validators_example"]),
            ("validationFailureLevel", ValidationLevel.INFO),
            ("dryrun", True),
            ("rollbackOnFailure", True),
            ("clientToken", "client_token_example"),
        ]
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        response = client.open(
            "/v3/clusters",
            method="POST",
            headers=headers,
            data=json.dumps(create_cluster_request_content),
            content_type="application/json",
            query_string=query_string,
        )
        assert_that(response.status_code).is_equal_to(200)


class TestDeleteCluster:
    def test_delete_cluster(self, client):
        query_string = [("region", "eu-west-1"), ("retainLogs", True), ("clientToken", "client_token_example")]
        headers = {
            "Accept": "application/json",
        }
        response = client.open(
            "/v3/clusters/{cluster_name}".format(cluster_name="clustername"),
            method="DELETE",
            headers=headers,
            query_string=query_string,
        )
        assert_that(response.status_code).is_equal_to(200)


class TestDescribeCluster:
    def test_describe_cluster(self, client):
        query_string = [("region", "eu-west-1")]
        headers = {
            "Accept": "application/json",
        }
        response = client.open(
            "/v3/clusters/{cluster_name}".format(cluster_name="clustername"),
            method="GET",
            headers=headers,
            query_string=query_string,
        )
        assert_that(response.status_code).is_equal_to(200)


class TestListClusters:
    def test_list_clusters(self, client):
        query_string = [
            ("region", "eu-west-1"),
            ("nextToken", "next_token_example"),
            ("clusterStatus", ClusterStatus.CREATE_COMPLETE),
        ]
        headers = {
            "Accept": "application/json",
        }
        response = client.open("/v3/clusters", method="GET", headers=headers, query_string=query_string)
        assert_that(response.status_code).is_equal_to(200)


class TestUpdateCluster:
    def test_update_cluster(self, client):
        update_cluster_request_content = {"clusterConfiguration": "clusterConfiguration"}
        query_string = [
            ("suppressValidators", ["suppress_validators_example"]),
            ["validationFailureLevel", ValidationLevel.INFO],
            ("region", "eu-west-1"),
            ("dryrun", True),
            ("forceUpdate", True),
            ("clientToken", "client_token_example"),
        ]
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        response = client.open(
            "/v3/clusters/{cluster_name}".format(cluster_name="clustername"),
            method="PUT",
            headers=headers,
            data=json.dumps(update_cluster_request_content),
            content_type="application/json",
            query_string=query_string,
        )
        assert_that(response.status_code).is_equal_to(200)
