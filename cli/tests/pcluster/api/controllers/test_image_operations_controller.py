#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import json

from assertpy import assert_that

from pcluster.api.models.image_build_status import ImageBuildStatus
from pcluster.api.models.validation_level import ValidationLevel


class TestImageOperationsController:
    """ImageOperationsController integration test stubs."""

    def test_build_image(self, client):
        """Test case for build_image."""
        build_image_request_content = {
            "imageConfiguration": "imageConfiguration",
            "id": "imageid",
            "region": "eu-west-1",
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
            "/v3/images/custom",
            method="POST",
            headers=headers,
            data=json.dumps(build_image_request_content),
            content_type="application/json",
            query_string=query_string,
        )
        assert_that(response.status_code).is_equal_to(200)

    def test_delete_image(self, client):
        """Test case for delete_image."""
        query_string = [("region", "eu-west-1"), ("clientToken", "client_token_example"), ("force", True)]
        headers = {
            "Accept": "application/json",
        }
        response = client.open(
            "/v3/images/custom/{image_id}".format(image_id="imageid"),
            method="DELETE",
            headers=headers,
            query_string=query_string,
        )
        assert_that(response.status_code).is_equal_to(200)

    def test_describe_image(self, client):
        """Test case for describe_image."""
        query_string = [("region", "eu-west-1")]
        headers = {
            "Accept": "application/json",
        }
        response = client.open(
            "/v3/images/custom/{image_id}".format(image_id="imageid"),
            method="GET",
            headers=headers,
            query_string=query_string,
        )
        assert_that(response.status_code).is_equal_to(200)

    def test_describe_official_images(self, client):
        """Test case for describe_official_images."""
        query_string = [
            ("version", "version_example"),
            ("region", "eu-west-1"),
            ("os", "os_example"),
            ("architecture", "architecture_example"),
            ("nextToken", "next_token_example"),
        ]
        headers = {
            "Accept": "application/json",
        }
        response = client.open("/v3/images/official", method="GET", headers=headers, query_string=query_string)
        assert_that(response.status_code).is_equal_to(200)

    def test_list_images(self, client):
        """Test case for list_images."""
        query_string = [
            ("region", "eu-west-1"),
            ("nextToken", "next_token_example"),
            ("imageStatus", ImageBuildStatus.BUILD_FAILED),
            ("imageStatus", ImageBuildStatus.BUILD_COMPLETE),
        ]
        headers = {
            "Accept": "application/json",
        }
        response = client.open("/v3/images/custom", method="GET", headers=headers, query_string=query_string)
        assert_that(response.status_code).is_equal_to(200)
