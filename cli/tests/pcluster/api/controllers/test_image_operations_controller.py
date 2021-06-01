#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import json

import pytest
from assertpy import assert_that, soft_assertions

from pcluster.api.models import CloudFormationStatus
from pcluster.api.models.image_build_status import ImageBuildStatus
from pcluster.api.models.validation_level import ValidationLevel
from pcluster.aws.aws_resources import ImageInfo
from pcluster.aws.common import ImageNotFoundError, StackNotFoundError
from pcluster.models.imagebuilder import ImageBuilderActionError


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
            ("imageStatus", ImageBuildStatus.BUILD_FAILED),
            ("imageStatus", ImageBuildStatus.BUILD_COMPLETE),
        ]
        headers = {
            "Accept": "application/json",
        }
        response = client.open("/v3/images/custom", method="GET", headers=headers, query_string=query_string)
        assert_that(response.status_code).is_equal_to(200)


class TestDeleteImage:
    url = "/v3/images/custom/{image_name}"
    method = "DELETE"

    def _send_test_request(self, client, image_name, region="us-east-1", force=True):
        query_string = [
            ("force", force),
            ("region", region),
        ]
        headers = {
            "Accept": "application/json",
        }
        return client.open(
            self.url.format(image_name=image_name), method=self.method, headers=headers, query_string=query_string
        )

    def _create_image_info(self, image_id):
        return ImageInfo(
            {
                "Tags": [
                    {"Key": "parallelcluster:image_id", "Value": image_id},
                    {"Key": "parallelcluster:version", "Value": "3.0.0"},
                ],
            }
        )

    def _create_stack(self, image_id, status):
        return {
            "StackId": "arn:{}".format(image_id),
            "StackStatus": status,
            "Tags": [
                {"Key": "parallelcluster:image_id", "Value": image_id},
                {"Key": "parallelcluster:version", "Value": "3.0.0"},
            ],
        }

    def _assert_successful(
        self, mocker, client, image_id, force, region, image, stack, expected_response, stack_after_deletion=None
    ):
        if image:
            mocker.patch("pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag", return_value=image)
        else:
            mocker.patch(
                "pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag",
                side_effect=ImageNotFoundError("describe_image_by_id_tag"),
            )

        if stack:
            if stack_after_deletion:
                mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", side_effect=[stack, stack_after_deletion])
            else:
                mocker.patch(
                    "pcluster.aws.cfn.CfnClient.describe_stack",
                    side_effect=[stack, StackNotFoundError("describe_stack", "stack_name")],
                )
        else:
            mocker.patch(
                "pcluster.aws.cfn.CfnClient.describe_stack",
                side_effect=StackNotFoundError("describe_stack", "stack_name"),
            )

        mocker.patch("pcluster.models.imagebuilder.ImageBuilder.delete", return_value=None)

        response = self._send_test_request(client, image_id, region, force)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            assert_that(response.get_json()).is_equal_to(expected_response)

    def test_delete_available_ec2_image_with_stack_yet_to_be_removed_succeeds(self, mocker, client):
        image = self._create_image_info("image1")
        stack = self._create_stack("image1", CloudFormationStatus.DELETE_IN_PROGRESS)
        expected_response = {
            "image": {
                "imageId": "image1",
                "imageBuildStatus": ImageBuildStatus.DELETE_COMPLETE,
                "region": "us-east-1",
                "version": "3.0.0",
            }
        }
        self._assert_successful(mocker, client, "image1", True, "us-east-1", image, stack, expected_response)

    def test_delete_available_ec2_image_with_stack_already_removed_succeeds(self, mocker, client):
        image = self._create_image_info("image1")
        expected_response = {
            "image": {
                "imageId": "image1",
                "imageBuildStatus": ImageBuildStatus.DELETE_COMPLETE,
                "region": "us-east-1",
                "version": "3.0.0",
            }
        }
        self._assert_successful(mocker, client, "image1", True, "us-east-1", image, None, expected_response)

    def test_delete_image_with_only_stack_and_no_available_image_succeeds(self, mocker, client):
        stack = self._create_stack("image1", CloudFormationStatus.DELETE_FAILED)
        stack_after_deletion = self._create_stack("image1", CloudFormationStatus.DELETE_IN_PROGRESS)
        expected_response = {
            "image": {
                "imageId": "image1",
                "imageBuildStatus": ImageBuildStatus.DELETE_IN_PROGRESS,
                "region": "us-east-1",
                "version": "3.0.0",
                "cloudformationStackStatus": CloudFormationStatus.DELETE_IN_PROGRESS,
                "cloudformationStackArn": "arn:image1",
            }
        }
        self._assert_successful(
            mocker, client, "image1", True, "us-east-1", None, stack, expected_response, stack_after_deletion
        )

    def test_delete_image_with_only_stack_when_stack_is_deleted_immediately(self, mocker, client):
        stack = self._create_stack("image1", CloudFormationStatus.DELETE_FAILED)
        expected_response = {
            "image": {
                "imageId": "image1",
                "imageBuildStatus": ImageBuildStatus.DELETE_COMPLETE,
                "region": "us-east-1",
                "version": "3.0.0",
                "cloudformationStackStatus": CloudFormationStatus.DELETE_COMPLETE,
                "cloudformationStackArn": "arn:image1",
            }
        }
        self._assert_successful(
            mocker, client, "image1", True, "us-east-1", None, stack, expected_response, stack_after_deletion=None
        )

    def test_delete_image_with_no_available_image_or_stack_throws_not_found_exception(self, mocker, client):
        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag",
            side_effect=ImageNotFoundError("describe_image_by_id_tag"),
        )
        mocker.patch(
            "pcluster.aws.cfn.CfnClient.describe_stack", side_effect=StackNotFoundError("describe_stack", "stack_name")
        )
        response = self._send_test_request(client, "nonExistentImage")

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(404)
            assert_that(response.get_json()).is_equal_to(
                {"message": "Unable to find an image of stack with id: nonExistentImage"}
            )

    @pytest.mark.parametrize(
        "region, image_id, force, expected_response",
        [
            pytest.param(
                "us-east-",
                "imageId",
                True,
                {"message": "Bad Request: invalid or unsupported region 'us-east-'"},
                id="bad_region",
            ),
            pytest.param(None, "imageId", True, {"message": "Bad Request: region needs to be set"}, id="unset_region"),
            pytest.param(
                "us-east-1",
                "_malformedImageId",
                True,
                {"message": "Bad Request: '_malformedImageId' does not match '^[a-zA-Z][a-zA-Z0-9-]+$'"},
                id="invalid_image_id",
            ),
        ],
    )
    def test_malformed_request(self, client, region, image_id, force, expected_response):
        response = self._send_test_request(client, image_id, region, force)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(400)
            assert_that(response.get_json()).is_equal_to(expected_response)

    def test_that_a_server_internal_error_is_thrown_if_the_delete_fails(self, client, mocker):
        image = self._create_image_info("image1")
        mocker.patch("pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag", return_value=image)
        mocker.patch(
            "pcluster.models.imagebuilder.ImageBuilder.delete", side_effect=ImageBuilderActionError("test error")
        )
        expected_error = {
            "message": "Unexpected fatal exception. Please look "
            "at the application logs for details on the encountered failure."
        }
        response = self._send_test_request(client, "image1")

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(500)
            assert_that(response.get_json()).is_equal_to(expected_error)
