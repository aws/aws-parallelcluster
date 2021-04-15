#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import json

from assertpy import assert_that

from api.models import ClusterStatus, ValidationLevel


class TestClusterOperationsController:
    """ClusterOperationsController integration test stubs."""

    def test_create_cluster(self, client):
        """Test case for create_cluster."""
        create_cluster_request_content = {
            "name": "clustername",
            "region": "region",
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

    def test_delete_cluster(self, client):
        """Test case for delete_cluster."""
        query_string = [("region", "region_example"), ("retainLogs", True), ("clientToken", "client_token_example")]
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

    def test_describe_cluster(self, client):
        """Test case for describe_cluster."""
        query_string = [("region", "region_example")]
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

    def test_list_clusters(self, client):
        """Test case for list_clusters."""
        query_string = [
            ("region", "region_example"),
            ("nextToken", "next_token_example"),
            ("clusterStatus", ClusterStatus.CREATE_COMPLETE),
        ]
        headers = {
            "Accept": "application/json",
        }
        response = client.open("/v3/clusters", method="GET", headers=headers, query_string=query_string)
        assert_that(response.status_code).is_equal_to(200)

    def test_update_cluster(self, client):
        """Test case for update_cluster."""
        update_cluster_request_content = {"clusterConfiguration": "clusterConfiguration"}
        query_string = [
            ("suppressValidators", ["suppress_validators_example"]),
            ["validationFailureLevel", ValidationLevel.INFO],
            ("region", "region_example"),
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
