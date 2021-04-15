#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
from assertpy import assert_that

from api.models import NodeType


class TestClusterInstancesController:
    """ClusterInstancesController integration test stubs."""

    def test_delete_cluster_instances(self, client):
        """Test case for delete_cluster_instances."""
        query_string = [("region", "region_example"), ("force", True)]
        headers = {
            "Accept": "application/json",
        }
        response = client.open(
            "/v3/clusters/{cluster_name}/instances".format(cluster_name="clustername"),
            method="DELETE",
            headers=headers,
            query_string=query_string,
        )
        assert_that(response.status_code).is_equal_to(204)

    def test_describe_cluster_instances(self, client):
        """Test case for describe_cluster_instances."""
        query_string = [
            ("region", "region_example"),
            ("nextToken", "next_token_example"),
            ("nodeType", NodeType.HEAD),
            ("queueName", "queue_name_example"),
        ]
        headers = {
            "Accept": "application/json",
        }
        response = client.open(
            "/v3/clusters/{cluster_name}/instances".format(cluster_name="clustername"),
            method="GET",
            headers=headers,
            query_string=query_string,
        )
        assert_that(response.status_code).is_equal_to(200)
