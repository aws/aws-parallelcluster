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

from pcluster.api.models import CloudFormationStatus, ImageBuildStatus, ImageStatusFilteringOption
from pcluster.api.models.validation_level import ValidationLevel
from pcluster.aws.aws_resources import ImageInfo
from pcluster.aws.common import (
    AWSClientError,
    BadRequestError,
    ImageNotFoundError,
    LimitExceededError,
    StackNotFoundError,
)
from pcluster.constants import OS_TO_IMAGE_NAME_PART_MAP, SUPPORTED_ARCHITECTURES, SUPPORTED_OSES
from pcluster.models.imagebuilder import (
    BadRequestImageBuilderActionError,
    BadRequestImageError,
    ConflictImageBuilderActionError,
    LimitExceededImageBuilderActionError,
    LimitExceededImageError,
)
from pcluster.models.imagebuilder_resources import BadRequestStackError, LimitExceededStackError
from pcluster.utils import get_installed_version
from pcluster.validators.common import FailureLevel, ValidationResult


class TestImageOperationsController:
    """ImageOperationsController integration test stubs."""

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


def _create_image_info(image_id):
    return ImageInfo(
        {
            "Tags": [
                {"Key": "parallelcluster:image_id", "Value": image_id},
                {"Key": "parallelcluster:version", "Value": "3.0.0"},
            ],
        }
    )


def _create_stack(image_id, status):
    return {
        "StackId": f"arn:{image_id}",
        "StackStatus": status,
        "Tags": [
            {"Key": "parallelcluster:image_id", "Value": image_id},
            {"Key": "parallelcluster:version", "Value": "3.0.0"},
        ],
    }


class TestListImages:
    url = "v3/images/custom"
    method = "GET"

    def _send_test_request(self, client, image_status, next_token=None, region="us-east-1"):
        query_string = []

        if region:
            query_string.append(("region", region))

        if image_status:
            query_string.append(("imageStatus", image_status))

        if next_token:
            query_string.append(("nextToken", next_token))

        headers = {
            "Accept": "application/json",
        }

        return client.open(self.url, method=self.method, headers=headers, query_string=query_string)

    def test_list_available_images_successful(self, client, mocker):
        describe_result = [
            _create_image_info("image1"),
            _create_image_info("image2"),
        ]
        expected_response = {
            "items": [
                {
                    "imageId": "image1",
                    "imageBuildStatus": ImageBuildStatus.BUILD_COMPLETE,
                    "region": "us-east-1",
                    "version": "3.0.0",
                },
                {
                    "imageId": "image2",
                    "imageBuildStatus": ImageBuildStatus.BUILD_COMPLETE,
                    "region": "us-east-1",
                    "version": "3.0.0",
                },
            ]
        }
        mocker.patch("pcluster.aws.ec2.Ec2Client.get_images", return_value=describe_result)

        response = self._send_test_request(client, ImageStatusFilteringOption.AVAILABLE)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize("next_token", [None, "nextToken"], ids=["nextToken is None", "nextToken is not None"])
    def test_list_pending_images_successful(self, client, mocker, next_token):
        describe_result = [
            _create_stack("image1", CloudFormationStatus.CREATE_COMPLETE),
            _create_stack("image2", CloudFormationStatus.CREATE_COMPLETE),
            _create_stack("image3", CloudFormationStatus.CREATE_IN_PROGRESS),
            _create_stack("image4", CloudFormationStatus.DELETE_IN_PROGRESS),
        ]
        mocker.patch("pcluster.aws.cfn.CfnClient.get_imagebuilder_stacks", return_value=(describe_result, "nextPage"))

        response = self._send_test_request(client, ImageStatusFilteringOption.PENDING, next_token)

        expected_response = {
            "items": [
                {
                    "imageId": "image3",
                    "imageBuildStatus": ImageBuildStatus.BUILD_IN_PROGRESS,
                    "cloudformationStackStatus": CloudFormationStatus.CREATE_IN_PROGRESS,
                    "cloudformationStackArn": "arn:image3",
                    "region": "us-east-1",
                    "version": "3.0.0",
                },
            ],
            "nextToken": "nextPage",
        }

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize("next_token", [None, "nextToken"], ids=["nextToken is None", "nextToken is not None"])
    def test_list_failed_images_successful(self, client, mocker, next_token):
        describe_result = [
            _create_stack("image1", CloudFormationStatus.CREATE_COMPLETE),
            _create_stack("image2", CloudFormationStatus.CREATE_COMPLETE),
            _create_stack("image3", CloudFormationStatus.CREATE_IN_PROGRESS),
            _create_stack("image4", CloudFormationStatus.DELETE_IN_PROGRESS),
            _create_stack("image5", CloudFormationStatus.DELETE_FAILED),
            _create_stack("image6", CloudFormationStatus.CREATE_FAILED),
        ]
        mocker.patch("pcluster.aws.cfn.CfnClient.get_imagebuilder_stacks", return_value=(describe_result, "nextPage"))

        response = self._send_test_request(client, ImageStatusFilteringOption.FAILED, next_token)

        expected_response = {
            "items": [
                {
                    "imageId": "image5",
                    "imageBuildStatus": ImageBuildStatus.DELETE_FAILED,
                    "cloudformationStackStatus": CloudFormationStatus.DELETE_FAILED,
                    "cloudformationStackArn": "arn:image5",
                    "region": "us-east-1",
                    "version": "3.0.0",
                },
                {
                    "imageId": "image6",
                    "imageBuildStatus": ImageBuildStatus.BUILD_FAILED,
                    "cloudformationStackStatus": CloudFormationStatus.CREATE_FAILED,
                    "cloudformationStackArn": "arn:image6",
                    "region": "us-east-1",
                    "version": "3.0.0",
                },
            ],
            "nextToken": "nextPage",
        }

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize(
        "region, image_status, expected_response",
        [
            pytest.param(
                "us-east-",
                "AVAILABLE",
                {"message": "Bad Request: invalid or unsupported region 'us-east-'"},
                id="bad region",
            ),
            pytest.param(None, "AVAILABLE", {"message": "Bad Request: region needs to be set"}, id="region not set"),
            pytest.param(
                "us-east-1",
                None,
                {"message": "Bad Request: Missing query parameter 'imageStatus'"},
                id="image status not set",
            ),
            pytest.param(
                "us-east-1",
                "UNAVAILABLE_STATE",
                {"message": "Bad Request: 'UNAVAILABLE_STATE' is not one of ['AVAILABLE', 'PENDING', 'FAILED']"},
                id="image status not among the valid ones",
            ),
        ],
    )
    def test_malformed_request(self, client, region, image_status, expected_response):
        response = self._send_test_request(client, image_status, region=region)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(400)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize(
        "error, status_code", [(LimitExceededError, 429), (BadRequestError, 400), (AWSClientError, 500)]
    )
    def test_that_errors_are_converted(self, client, mocker, error, status_code):
        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.get_images", side_effect=error(function_name="get_images", message="test error")
        )
        expected_error = {"message": "test error"}
        if error == BadRequestError:
            expected_error["message"] = "Bad Request: " + expected_error["message"]
        response = self._send_test_request(client, ImageStatusFilteringOption.AVAILABLE)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(status_code)
            assert_that(response.get_json()).is_equal_to(expected_error)


class TestDeleteImage:
    url = "/v3/images/custom/{image_name}"
    method = "DELETE"

    def _send_test_request(self, client, image_name, region="us-east-1", force=True, client_token=None):
        query_string = [
            ("force", force),
            ("region", region),
        ]
        if client_token:
            query_string.append(("clientToken", client_token))
        headers = {
            "Accept": "application/json",
        }
        return client.open(
            self.url.format(image_name=image_name), method=self.method, headers=headers, query_string=query_string
        )

    def _assert_successful(self, mocker, client, image_id, force, region, image, stack, expected_response):
        if image:
            mocker.patch("pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag", return_value=image)
        else:
            mocker.patch(
                "pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag",
                side_effect=ImageNotFoundError("describe_image_by_id_tag"),
            )

        if stack:
            mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", return_value=stack)
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
        image = _create_image_info("image1")
        stack = _create_stack("image1", CloudFormationStatus.DELETE_IN_PROGRESS)
        expected_response = {
            "image": {
                "imageId": "image1",
                "imageBuildStatus": ImageBuildStatus.DELETE_IN_PROGRESS,
                "region": "us-east-1",
                "version": "3.0.0",
            }
        }
        self._assert_successful(mocker, client, "image1", True, "us-east-1", image, stack, expected_response)

    def test_delete_available_ec2_image_with_stack_already_removed_succeeds(self, mocker, client):
        image = _create_image_info("image1")
        expected_response = {
            "image": {
                "imageId": "image1",
                "imageBuildStatus": ImageBuildStatus.DELETE_IN_PROGRESS,
                "region": "us-east-1",
                "version": "3.0.0",
            }
        }
        self._assert_successful(mocker, client, "image1", True, "us-east-1", image, None, expected_response)

    def test_delete_image_with_only_stack_and_no_available_image_succeeds(self, mocker, client):
        stack = _create_stack("image1", CloudFormationStatus.DELETE_FAILED)
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
        self._assert_successful(mocker, client, "image1", True, "us-east-1", None, stack, expected_response)

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
                {"message": "Unable to find an image or stack for ParallelCluster image id: nonExistentImage"}
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

    @pytest.mark.parametrize("error", [BadRequestImageError, BadRequestStackError, BadRequestImageBuilderActionError])
    def test_that_imagebuilder_bad_request_error_is_converted(self, client, mocker, error):
        image = _create_image_info("image1")
        mocker.patch("pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag", return_value=image)
        mocker.patch(
            "pcluster.models.imagebuilder.ImageBuilder.delete",
            side_effect=error("test error"),
        )
        expected_error = {"message": "Bad Request: test error"}
        response = self._send_test_request(client, "image1")

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(400)
            assert_that(response.get_json()).is_equal_to(expected_error)

    @pytest.mark.parametrize(
        "error", [LimitExceededImageError, LimitExceededStackError, LimitExceededImageBuilderActionError]
    )
    def test_that_limit_exceeded_error_is_converted(self, client, mocker, error):
        image = _create_image_info("image1")
        mocker.patch("pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag", return_value=image)
        mocker.patch("pcluster.models.imagebuilder.ImageBuilder.delete", side_effect=error("test error"))
        expected_error = {"message": "test error"}
        response = self._send_test_request(client, "image1")

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(429)
            assert_that(response.get_json()).is_equal_to(expected_error)

    def test_that_other_errors_are_converted(self, client, mocker):
        image = _create_image_info("image1")
        mocker.patch("pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag", return_value=image)
        mocker.patch("pcluster.models.imagebuilder.ImageBuilder.delete", side_effect=Exception("test error"))
        expected_error = {"message": "test error"}
        response = self._send_test_request(client, "image1")

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(500)
            assert_that(response.get_json()).is_equal_to(expected_error)

    def test_that_call_with_client_token_throws_bad_request(self, client):
        expected_error = {"message": "Bad Request: clientToken is currently not supported for this operation"}
        response = self._send_test_request(client, "image1", client_token="clientToken")

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(400)
            assert_that(response.get_json()).is_equal_to(expected_error)


class TestBuildImage:
    url = "/v3/images/custom"
    method = "POST"
    encoded_config = (
        "QnVpbGQ6CiAgSW5zdGFuY2VUeXBlOiBjNS54bGFyZ2UKICBQYXJlbnRJbWFnZTogYXJuOmF"
        "3czppbWFnZWJ1aWxkZXI6dXMtZWFzdC0xOmF3czppbWFnZS9hbWF6b24tbGludXgtMi14OD"
        "YveC54LngKCkRldlNldHRpbmdzOgogIENvb2tib29rOgogICAgQ2hlZkNvb2tib29rOiBod"
        "HRwczovL2dpdGh1Yi5jb20vYXdzL2F3cy1wYXJhbGxlbGNsdXN0ZXItY29va2Jvb2svdGFy"
        "YmFsbC8yNmFiODQyM2I4NGRlMWEwOThiYzI2ZThmZjE3NjhlOTMwZmM3NzA3CiAgTm9kZVB"
        "hY2thZ2U6IGh0dHBzOi8vZ2l0aHViLmNvbS9hd3MvYXdzLXBhcmFsbGVsY2x1c3Rlci1ub2"
        "RlL3RhcmJhbGwvODc1ZWY5Mzk4NmE4NmVhMzI2NzgzNWE4MTNkMzhlYWEwNWU1NzVmMwogI"
        "EF3c0JhdGNoQ2xpUGFja2FnZTogaHR0cHM6Ly9naXRodWIuY29tL2F3cy9hd3MtcGFyYWxs"
        "ZWxjbHVzdGVyL3RhcmJhbGwvZDVjMmExZWMyNjdhODY1Y2ZmM2NmMzUwYWYzMGQ0NGU2OGYwZWYxOA===="
    )

    def _send_test_request(self, client, dryrun=False, client_token=None):
        build_image_request_content = {
            "imageConfiguration": self.encoded_config,
            "id": "imageid",
            "region": "eu-west-1",
        }
        query_string = [
            ("suppressValidators", ["suppress_validators_example"]),
            ("validationFailureLevel", ValidationLevel.INFO),
            ("dryrun", dryrun),
            ("rollbackOnFailure", True),
        ]
        if client_token:
            query_string.append(("clientToken", client_token))
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        return client.open(
            self.url,
            method=self.method,
            data=json.dumps(build_image_request_content),
            headers=headers,
            query_string=query_string,
            content_type="application/json",
        )

    @pytest.mark.parametrize(
        "suppressed_validation_errors",
        [[], [ValidationResult("suppressed failure", FailureLevel.INFO, "dummy validator")]],
        ids=["test with no validation errors", "test with validation errors"],
    )
    def test_build_image_success(self, client, mocker, suppressed_validation_errors):
        mocker.patch("pcluster.models.imagebuilder.ImageBuilder.create", return_value=suppressed_validation_errors)
        mocker.patch(
            "pcluster.aws.cfn.CfnClient.describe_stack",
            return_value=_create_stack("image1", CloudFormationStatus.CREATE_IN_PROGRESS),
        )

        expected_response = {
            "image": {
                "cloudformationStackArn": "arn:image1",
                "cloudformationStackStatus": "CREATE_IN_PROGRESS",
                "imageBuildStatus": "BUILD_IN_PROGRESS",
                "imageId": "image1",
                "region": "eu-west-1",
                "version": "3.0.0",
            }
        }

        if suppressed_validation_errors:
            expected_response["validationMessages"] = [
                {"level": "INFO", "type": "dummy validator", "message": "suppressed failure"}
            ]

        response = self._send_test_request(client, dryrun=False)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize(
        "validation_errors, error_code, expected_response",
        [
            pytest.param(
                None, 412, {"message": "Request would have succeeded, but DryRun flag is set."}, id="test success"
            ),
            pytest.param(
                BadRequestImageBuilderActionError(
                    "test validation error", [ValidationResult("test failure", FailureLevel.ERROR, "dummy validator")]
                ),
                400,
                {
                    "configuration_validation_errors": [
                        {"level": "ERROR", "id": None, "type": "dummy validator", "message": "test failure"}
                    ],
                    "message": "test validation error",
                },
                id="test validation failure",
            ),
            pytest.param(
                ConflictImageBuilderActionError("test error"), 409, {"message": "test error"}, id="test conflict error"
            ),
        ],
    )
    def test_dryrun(self, client, mocker, validation_errors, error_code, expected_response):
        if validation_errors:
            mocker.patch(
                "pcluster.models.imagebuilder.ImageBuilder.validate_create_request", side_effect=validation_errors
            )
        else:
            mocker.patch("pcluster.models.imagebuilder.ImageBuilder.validate_create_request", return_value=None)

        response = self._send_test_request(client, dryrun=True)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(error_code)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize(
        "error, error_code",
        [
            (LimitExceededImageError, 429),
            (LimitExceededStackError, 429),
            (LimitExceededImageBuilderActionError, 429),
            (BadRequestImageError, 400),
            (BadRequestStackError, 400),
            (BadRequestImageBuilderActionError, 400),
            (ConflictImageBuilderActionError, 409),
        ],
    )
    def test_that_errors_are_converted(self, client, mocker, error, error_code):
        mocker.patch("pcluster.models.imagebuilder.ImageBuilder.create", side_effect=(error("test error")))
        expected_error = {"message": "test error"}
        if error in {BadRequestImageError, BadRequestStackError}:
            expected_error["message"] = "Bad Request: " + expected_error["message"]
        if error == BadRequestImageBuilderActionError:
            expected_error["configuration_validation_errors"] = []
        response = self._send_test_request(client, dryrun=False)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(error_code)
            assert_that(response.get_json()).is_equal_to(expected_error)

    def test_that_call_with_client_token_throws_bad_request(self, client):
        expected_error = {
            "configuration_validation_errors": [],
            "message": "clientToken is currently not supported for this operation",
        }
        response = self._send_test_request(client, client_token="clientToken")

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(400)
            assert_that(response.get_json()).is_equal_to(expected_error)


def _create_official_image_info(version, os, architecture):
    return ImageInfo(
        {
            "Name": f"aws-parallelcluster-{version}-{OS_TO_IMAGE_NAME_PART_MAP[os]}-{architecture}-other",
            "Architecture": "x86_64",
            "ImageId": "ami-test",
        }
    )


def _describe_official_images_expected_response(version, os, architecture):
    return {
        "amiId": "ami-test",
        "os": os,
        "name": f"aws-parallelcluster-{version}-{OS_TO_IMAGE_NAME_PART_MAP[os]}-{architecture}-other",
        "architecture": architecture,
        "version": get_installed_version(),
    }


class TestDescribeOfficialImages:
    def _send_test_request(self, client, os=None, architecture=None, region="us-east-1"):
        query_string = [
            ("region", region),
            ("os", os),
            ("architecture", architecture),
        ]
        headers = {
            "Accept": "application/json",
        }
        return client.open("/v3/images/official", method="GET", headers=headers, query_string=query_string)

    @pytest.mark.parametrize(
        "os, arch, mocked_response, expected_response",
        [
            pytest.param(
                None,
                None,
                [_create_official_image_info("3.0.0", "alinux2", "x86_64")],
                {"items": [_describe_official_images_expected_response("3.0.0", "alinux2", "x86_64")]},
                id="test with no arguments",
            ),
            pytest.param(
                "alinux2",
                None,
                [_create_official_image_info("3.0.0", "alinux2", "x86_64")],
                {"items": [_describe_official_images_expected_response("3.0.0", "alinux2", "x86_64")]},
                id="test with os",
            ),
            pytest.param(
                None,
                "x86_64",
                [_create_official_image_info("3.0.0", "alinux2", "x86_64")],
                {"items": [_describe_official_images_expected_response("3.0.0", "alinux2", "x86_64")]},
                id="test with architecture",
            ),
            pytest.param(
                "alinux2",
                "x86_64",
                [_create_official_image_info("3.0.0", "alinux2", "x86_64")],
                {"items": [_describe_official_images_expected_response("3.0.0", "alinux2", "x86_64")]},
                id="test with os and architecture",
            ),
        ],
    )
    def test_describe_successful(self, client, mocker, os, arch, mocked_response, expected_response):
        mocker.patch("pcluster.aws.ec2.Ec2Client.get_official_images", return_value=mocked_response)
        response = self._send_test_request(client, os, arch)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize(
        "region, os, architecture, expected_response",
        [
            pytest.param(
                "us-east-",
                None,
                None,
                {"message": "Bad Request: invalid or unsupported region 'us-east-'"},
                id="test with malformed region",
            ),
            pytest.param(
                None, None, None, {"message": "Bad Request: region needs to be set"}, id="test without region"
            ),
            pytest.param(
                "us-east-1",
                "nonExistentOs",
                None,
                {"message": f"Bad Request: nonExistentOs is not one of {SUPPORTED_OSES}"},
                id="test with malformed os",
            ),
            pytest.param(
                "us-east-1",
                None,
                "nonExistentArchitecture",
                {"message": f"Bad Request: nonExistentArchitecture is not one of {SUPPORTED_ARCHITECTURES}"},
                id="test with malformed architecture",
            ),
            pytest.param(
                "us-east-1",
                "nonExistentOs",
                "nonExistentArchitecture",
                {
                    "message": f"Bad Request: nonExistentOs is not one of {SUPPORTED_OSES}; "
                    f"nonExistentArchitecture is not one of {SUPPORTED_ARCHITECTURES}"
                },
                id="test with malformed os and architecture",
            ),
        ],
    )
    def test_malformed_request(self, client, region, os, architecture, expected_response):
        response = self._send_test_request(client, region=region, os=os, architecture=architecture)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(400)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize(
        "error, status_code", [(LimitExceededError, 429), (BadRequestError, 400), (AWSClientError, 500)]
    )
    def test_that_errors_are_converted(self, client, mocker, error, status_code):
        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.get_official_images",
            side_effect=error(function_name="get_official_images", message="test error"),
        )
        expected_error = {"message": "test error"}
        if error == BadRequestError:
            expected_error["message"] = "Bad Request: " + expected_error["message"]
        response = self._send_test_request(client)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(status_code)
            assert_that(response.get_json()).is_equal_to(expected_error)
