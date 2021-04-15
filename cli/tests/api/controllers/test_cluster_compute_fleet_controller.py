#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
from assertpy import assert_that
from flask import json


class TestClusterComputeFleetController:
    """ClusterComputeFleetController integration test stubs."""

    def test_describe_compute_fleet_status(self, client):
        """Test case for describe_compute_fleet_status."""
        query_string = [("region", "region_example")]
        headers = {
            "Accept": "application/json",
        }
        response = client.open(
            "/v3/clusters/{cluster_name}/computefleet/status".format(cluster_name="clustername"),
            method="GET",
            headers=headers,
            query_string=query_string,
        )
        assert_that(response.status_code).is_equal_to(200)

    def test_update_compute_fleet_status(self, client):
        """Test case for update_compute_fleet_status."""
        update_compute_fleet_status_request_content = {"status": "STOP_REQUESTED"}
        query_string = [("region", "region_example")]
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        response = client.open(
            "/v3/clusters/{cluster_name}/computefleet/status".format(cluster_name="clustername"),
            method="PATCH",
            headers=headers,
            data=json.dumps(update_compute_fleet_status_request_content),
            content_type="application/json",
            query_string=query_string,
        )
        assert_that(response.status_code).is_equal_to(204)
