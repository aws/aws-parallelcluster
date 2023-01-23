#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import json
from datetime import datetime

import pytest
from assertpy import assert_that, soft_assertions
from marshmallow.exceptions import ValidationError

from pcluster.api.models import (
    CloudFormationStackStatus,
    Ec2AmiState,
    ImageBuilderImageStatus,
    ImageBuildStatus,
    ImageStatusFilteringOption,
)
from pcluster.api.models.validation_level import ValidationLevel
from pcluster.aws.aws_resources import ImageInfo
from pcluster.aws.common import (
    AWSClientError,
    BadRequestError,
    ImageNotFoundError,
    LimitExceededError,
    StackNotFoundError,
)
from pcluster.constants import OS_TO_IMAGE_NAME_PART_MAP, SUPPORTED_ARCHITECTURES, SUPPORTED_OSES, Operation
from pcluster.models.imagebuilder import (
    BadRequestImageBuilderActionError,
    BadRequestImageError,
    ConflictImageBuilderActionError,
    LimitExceededImageBuilderActionError,
    LimitExceededImageError,
)
from pcluster.models.imagebuilder_resources import BadRequestStackError, LimitExceededStackError
from pcluster.utils import get_installed_version, to_iso_timestr, to_utc_datetime
from pcluster.validators.common import FailureLevel, ValidationResult
from tests.pcluster.api.controllers.utils import mock_assert_supported_operation, verify_unsupported_operation


def _create_image_info(image_id):
    return ImageInfo(
        {
            "Name": image_id,
            "ImageId": image_id,
            "State": Ec2AmiState.AVAILABLE,
            "Architecture": "x86_64",
            "CreationDate": datetime(2021, 4, 12),
            "Description": "description",
            "Tags": [
                {"Key": "parallelcluster:image_id", "Value": image_id},
                {"Key": "parallelcluster:version", "Value": "3.0.0"},
                {"Key": "parallelcluster:build_config", "Value": "s3://bucket/key"},
            ],
        }
    )


def _create_stack(image_id, status, reason=None):
    stack = {
        "StackId": f"arn:{image_id}",
        "StackName": f"arn:{image_id}",
        "StackStatus": status,
        "CreationTime": datetime(2021, 4, 12),
        "Tags": [
            {"Key": "parallelcluster:image_id", "Value": image_id},
            {"Key": "parallelcluster:version", "Value": "3.0.0"},
            {"Key": "parallelcluster:build_config", "Value": "s3://bucket/key"},
            {"Key": "parallelcluster:build_log", "Value": f"arn:{image_id}:build_log"},
        ],
    }

    if reason:
        stack["StackStatusReason"] = reason

    return stack


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

        headers = {"Accept": "application/json"}

        return client.open(self.url, method=self.method, headers=headers, query_string=query_string)

    def test_list_available_images_successful(self, client, mocker):
        describe_result = [_create_image_info("image1"), _create_image_info("image2")]
        expected_response = {
            "images": [
                {
                    "imageId": "image1",
                    "ec2AmiInfo": {"amiId": "image1"},
                    "imageBuildStatus": ImageBuildStatus.BUILD_COMPLETE,
                    "region": "us-east-1",
                    "version": "3.0.0",
                },
                {
                    "imageId": "image2",
                    "ec2AmiInfo": {"amiId": "image2"},
                    "imageBuildStatus": ImageBuildStatus.BUILD_COMPLETE,
                    "region": "us-east-1",
                    "version": "3.0.0",
                },
            ]
        }
        mocker.patch("pcluster.aws.ec2.Ec2Client.get_images", return_value=describe_result)

        # Ensure we don't hit AWS when creating ImageBuilderStack(s)
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack_resource", return_value=None)

        response = self._send_test_request(client, ImageStatusFilteringOption.AVAILABLE)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize("next_token", [None, "nextToken"], ids=["nextToken is None", "nextToken is not None"])
    def test_list_pending_images_successful(self, client, mocker, next_token):
        describe_result = [
            _create_stack("image1", CloudFormationStackStatus.CREATE_COMPLETE),
            _create_stack("image2", CloudFormationStackStatus.CREATE_COMPLETE),
            _create_stack("image3", CloudFormationStackStatus.CREATE_IN_PROGRESS),
            _create_stack("image4", CloudFormationStackStatus.DELETE_IN_PROGRESS),
        ]
        mocker.patch("pcluster.aws.cfn.CfnClient.get_imagebuilder_stacks", return_value=(describe_result, "nextPage"))

        # Ensure we don't hit AWS when creating ImageBuilderStack(s)
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack_resource", return_value=None)

        response = self._send_test_request(client, ImageStatusFilteringOption.PENDING, next_token)

        expected_response = {
            "images": [
                {
                    "imageId": "image3",
                    "imageBuildStatus": ImageBuildStatus.BUILD_IN_PROGRESS,
                    "cloudformationStackStatus": CloudFormationStackStatus.CREATE_IN_PROGRESS,
                    "cloudformationStackArn": "arn:image3",
                    "region": "us-east-1",
                    "version": "3.0.0",
                }
            ],
            "nextToken": "nextPage",
        }

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize("next_token", [None, "nextToken"], ids=["nextToken is None", "nextToken is not None"])
    def test_list_failed_images_successful(self, client, mocker, next_token):
        describe_result = [
            _create_stack("image1", CloudFormationStackStatus.CREATE_COMPLETE),
            _create_stack("image2", CloudFormationStackStatus.CREATE_COMPLETE),
            _create_stack("image3", CloudFormationStackStatus.CREATE_IN_PROGRESS),
            _create_stack("image4", CloudFormationStackStatus.DELETE_IN_PROGRESS),
            _create_stack("image5", CloudFormationStackStatus.DELETE_FAILED),
            _create_stack("image6", CloudFormationStackStatus.CREATE_FAILED),
            _create_stack("image7", CloudFormationStackStatus.ROLLBACK_FAILED),
            _create_stack("image8", CloudFormationStackStatus.ROLLBACK_COMPLETE),
            _create_stack("image9", CloudFormationStackStatus.ROLLBACK_IN_PROGRESS),
        ]
        mocker.patch("pcluster.aws.cfn.CfnClient.get_imagebuilder_stacks", return_value=(describe_result, "nextPage"))

        # Ensure we don't hit AWS when creating ImageBuilderStack(s)
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack_resource", return_value=None)

        response = self._send_test_request(client, ImageStatusFilteringOption.FAILED, next_token)

        expected_response = {
            "images": [
                {
                    "imageId": "image5",
                    "imageBuildStatus": ImageBuildStatus.DELETE_FAILED,
                    "cloudformationStackStatus": CloudFormationStackStatus.DELETE_FAILED,
                    "cloudformationStackArn": "arn:image5",
                    "region": "us-east-1",
                    "version": "3.0.0",
                },
                {
                    "imageId": "image6",
                    "imageBuildStatus": ImageBuildStatus.BUILD_FAILED,
                    "cloudformationStackStatus": CloudFormationStackStatus.CREATE_FAILED,
                    "cloudformationStackArn": "arn:image6",
                    "region": "us-east-1",
                    "version": "3.0.0",
                },
                {
                    "imageId": "image7",
                    "imageBuildStatus": ImageBuildStatus.BUILD_FAILED,
                    "cloudformationStackStatus": CloudFormationStackStatus.ROLLBACK_FAILED,
                    "cloudformationStackArn": "arn:image7",
                    "region": "us-east-1",
                    "version": "3.0.0",
                },
                {
                    "imageId": "image8",
                    "imageBuildStatus": ImageBuildStatus.BUILD_FAILED,
                    "cloudformationStackStatus": CloudFormationStackStatus.ROLLBACK_COMPLETE,
                    "cloudformationStackArn": "arn:image8",
                    "region": "us-east-1",
                    "version": "3.0.0",
                },
                {
                    "imageId": "image9",
                    "imageBuildStatus": ImageBuildStatus.BUILD_FAILED,
                    "cloudformationStackStatus": CloudFormationStackStatus.ROLLBACK_IN_PROGRESS,
                    "cloudformationStackArn": "arn:image9",
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

    def test_unsupported_operation_error(self, client, mocker):
        mocked_assert_supported_operation = mock_assert_supported_operation(
            mocker, "pcluster.api.controllers.image_operations_controller.assert_supported_operation"
        )
        response = self._send_test_request(client, ImageStatusFilteringOption.AVAILABLE)
        verify_unsupported_operation(
            mocked_assertion=mocked_assert_supported_operation,
            operation=Operation.LIST_IMAGES,
            region="us-east-1",
            response=response,
        )


class TestDeleteImage:
    url = "/v3/images/custom/{image_name}"
    method = "DELETE"

    def _send_test_request(self, client, image_name, region="us-east-1", force=True):
        query_string = [("force", force), ("region", region)]
        headers = {"Accept": "application/json"}
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

        # Ensure we don't hit AWS when creating ImageBuilderStack(s)
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack_resource", return_value=None)

        response = self._send_test_request(client, image_id, region, force)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(202)
            assert_that(response.get_json()).is_equal_to(expected_response)

    def test_delete_available_ec2_image_with_stack_yet_to_be_removed_succeeds(self, mocker, client):
        image = _create_image_info("image1")
        stack = _create_stack("image1", CloudFormationStackStatus.DELETE_IN_PROGRESS)
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
        stack = _create_stack("image1", CloudFormationStackStatus.DELETE_FAILED)
        expected_response = {
            "image": {
                "imageId": "image1",
                "imageBuildStatus": ImageBuildStatus.DELETE_IN_PROGRESS,
                "region": "us-east-1",
                "version": "3.0.0",
                "cloudformationStackStatus": CloudFormationStackStatus.DELETE_IN_PROGRESS,
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
                {"message": "No image or stack associated with ParallelCluster image id: nonExistentImage."}
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
        mocker.patch("pcluster.models.imagebuilder.ImageBuilder.delete", side_effect=error("test error"))
        expected_error = {"message": "Bad Request: test error"}
        response = self._send_test_request(client, "image1")

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(400)
            assert_that(response.get_json()).is_equal_to(expected_error)

    @pytest.mark.parametrize(
        "instance_using, image_is_shared, expected_response",
        [(True, False, r"Image.*is used by instances"), (False, True, r"Image.*is shared with accounts")],
    )
    def test_delete_using_shared_image(self, client, mocker, instance_using, image_is_shared, expected_response):
        image = _create_image_info("image1")
        mocker.patch("pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag", return_value=image)
        instances = ["id1"] if instance_using else []
        mocker.patch("pcluster.aws.ec2.Ec2Client.get_instance_ids_by_ami_id", return_value=instances)
        accounts = ["acct_1"] if image_is_shared else []
        mocker.patch("pcluster.aws.ec2.Ec2Client.get_image_shared_account_ids", return_value=accounts)

        response = self._send_test_request(client, "image1", force=False)
        with soft_assertions():
            assert_that(response.status_code).is_equal_to(400)
            assert_that(response.get_json()).contains("message")
            assert_that(response.get_json()["message"]).matches(expected_response)

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

    def test_unsupported_operation_error(self, client, mocker):
        mocked_assert_supported_operation = mock_assert_supported_operation(
            mocker, "pcluster.api.controllers.image_operations_controller.assert_supported_operation"
        )
        response = self._send_test_request(client, "image1")
        verify_unsupported_operation(
            mocked_assertion=mocked_assert_supported_operation,
            operation=Operation.DELETE_IMAGE,
            region="us-east-1",
            response=response,
        )


class TestBuildImage:
    url = "/v3/images/custom"
    method = "POST"
    config = (
        "Build:\n  InstanceType: c5.xlarge\n  ParentImage: arn:aws:imagebuilder:us-east-1:aws:image/amazon-"
        "linux-2-x86/x.x.x"
        "\n\nDevSettings:\n  Cookbook:\n    ChefCookbook: https://github.com/aws/aws-par"
        "allelcluster-cookbook/tarball/26ab8423b84de1a098bc26e8ff1768e930fc7707\n  NodePackage: https://git"
        "hub.com/aws/aws-parallelcluster-node/tarball/875ef93986a86ea3267835a813d38eaa05e575f3\n  AwsBatchC"
        "liPackage: https://github.com/aws/aws-parallelcluster/tarball/d5c2a1ec267a865cff3cf350af30d44e68f0"
        "ef18"
    )

    def _send_test_request(self, client, dryrun=None, suppress_validators=None, rollback_on_failure=None):
        build_image_request_content = {"imageConfiguration": self.config, "imageId": "imageid"}
        query_string = [("validationFailureLevel", ValidationLevel.INFO), ("region", "eu-west-1")]

        if dryrun is not None:
            query_string.append(("dryrun", dryrun))

        if rollback_on_failure is not None:
            query_string.append(("rollbackOnFailure", rollback_on_failure))

        if suppress_validators:
            query_string.extend([("suppressValidators", validator) for validator in suppress_validators])

        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        return client.open(
            self.url,
            method=self.method,
            data=json.dumps(build_image_request_content),
            headers=headers,
            query_string=query_string,
            content_type="application/json",
        )

    @pytest.mark.parametrize(
        "suppress_validators, suppressed_validation_errors, rollback_on_failure",
        [
            (None, None, None),
            (["type:type1", "type:type2"], [ValidationResult("suppressed failure", FailureLevel.INFO, "type1")], None),
            (None, None, False),
        ],
        ids=["test with no validation errors", "test with suppressed validators", "rollback on failure"],
    )
    def test_build_image_success(
        self, client, mocker, suppress_validators, suppressed_validation_errors, rollback_on_failure
    ):
        mocked_call = mocker.patch(
            "pcluster.models.imagebuilder.ImageBuilder.create",
            return_value=suppressed_validation_errors,
        )
        mocker.patch(
            "pcluster.aws.cfn.CfnClient.describe_stack",
            return_value=_create_stack("image1", CloudFormationStackStatus.CREATE_IN_PROGRESS),
        )
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack_resource", return_value=None)

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
                {"level": "INFO", "type": "type1", "message": "suppressed failure"}
            ]

        response = self._send_test_request(
            client, dryrun=False, suppress_validators=suppress_validators, rollback_on_failure=rollback_on_failure
        )

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(202)
            assert_that(response.get_json()).is_equal_to(expected_response)

        mocked_call.assert_called_with(
            disable_rollback=not rollback_on_failure if rollback_on_failure is not None else True,
            validator_suppressors=mocker.ANY,
            validation_failure_level=FailureLevel[ValidationLevel.INFO],
        )
        mocked_call.assert_called_once()
        if suppress_validators:
            _, kwargs = mocked_call.call_args
            assert_that(kwargs["validator_suppressors"].pop()._validators_to_suppress).is_equal_to({"type1", "type2"})

        mocked_call.assert_called_once()

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
                    "configurationValidationErrors": [
                        {"level": "ERROR", "type": "dummy validator", "message": "test failure"}
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
            (LimitExceededImageError("test error"), 429),
            (LimitExceededStackError("test error"), 429),
            (LimitExceededImageBuilderActionError("test error"), 429),
            (BadRequestImageError("test error"), 400),
            (BadRequestStackError("test error"), 400),
            (BadRequestImageBuilderActionError("test error", []), 400),
            (
                BadRequestImageBuilderActionError(
                    "test error", [ValidationResult("message", FailureLevel.WARNING, "type")]
                ),
                400,
            ),
            (ConflictImageBuilderActionError("test error"), 409),
        ],
    )
    def test_that_errors_are_converted(self, client, mocker, error, error_code):
        mocker.patch("pcluster.models.imagebuilder.ImageBuilder.create", side_effect=error)
        expected_error = {"message": "test error"}

        if isinstance(error, (BadRequestImageError, BadRequestStackError)):
            expected_error["message"] = "Bad Request: " + expected_error["message"]

        if isinstance(error, BadRequestImageBuilderActionError) and error.validation_failures:
            expected_error["configurationValidationErrors"] = [
                {"level": "WARNING", "message": "message", "type": "type"}
            ]

        response = self._send_test_request(client, dryrun=False)

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(error_code)
            assert_that(response.get_json()).is_equal_to(expected_error)

    def test_parse_config_error(self, client, mocker):
        mocker.patch("pcluster.aws.ec2.Ec2Client.image_exists", return_value=False)
        mocker.patch("pcluster.aws.cfn.CfnClient.stack_exists", return_value=False)
        mocker.patch("marshmallow.Schema.load", side_effect=ValidationError(message={"Error": "error"}))
        response = self._send_test_request(client)
        assert_that(response.status_code).is_equal_to(400)
        assert_that(response.get_json()["message"]).matches("Invalid image configuration.")

    def test_unsupported_operation_error(self, client, mocker):
        mocked_assert_supported_operation = mock_assert_supported_operation(
            mocker, "pcluster.api.controllers.image_operations_controller.assert_supported_operation"
        )
        response = self._send_test_request(client)
        verify_unsupported_operation(
            mocked_assertion=mocked_assert_supported_operation,
            operation=Operation.BUILD_IMAGE,
            region="eu-west-1",
            response=response,
        )


def _create_official_image_info(version, os, architecture):
    return ImageInfo(
        {
            "Name": f"aws-parallelcluster-{version}-{OS_TO_IMAGE_NAME_PART_MAP[os]}-{architecture}-other",
            "Architecture": "x86_64",
            "ImageId": "ami-test",
        }
    )


def _list_official_images_expected_response(version, os, architecture):
    return {
        "amiId": "ami-test",
        "os": os,
        "name": f"aws-parallelcluster-{version}-{OS_TO_IMAGE_NAME_PART_MAP[os]}-{architecture}-other",
        "architecture": architecture,
        "version": get_installed_version(),
    }


class TestListOfficialImages:
    def _send_test_request(self, client, os=None, architecture=None, region="us-east-1"):
        query_string = [("region", region), ("os", os), ("architecture", architecture)]
        headers = {"Accept": "application/json"}
        return client.open("/v3/images/official", method="GET", headers=headers, query_string=query_string)

    @pytest.mark.parametrize(
        "os, arch, mocked_response, expected_response",
        [
            pytest.param(
                None,
                None,
                [_create_official_image_info("3.0.0", "alinux2", "x86_64")],
                {"images": [_list_official_images_expected_response("3.0.0", "alinux2", "x86_64")]},
                id="test with no arguments",
            ),
            pytest.param(
                "alinux2",
                None,
                [_create_official_image_info("3.0.0", "alinux2", "x86_64")],
                {"images": [_list_official_images_expected_response("3.0.0", "alinux2", "x86_64")]},
                id="test with os",
            ),
            pytest.param(
                None,
                "x86_64",
                [_create_official_image_info("3.0.0", "alinux2", "x86_64")],
                {"images": [_list_official_images_expected_response("3.0.0", "alinux2", "x86_64")]},
                id="test with architecture",
            ),
            pytest.param(
                "alinux2",
                "x86_64",
                [_create_official_image_info("3.0.0", "alinux2", "x86_64")],
                {"images": [_list_official_images_expected_response("3.0.0", "alinux2", "x86_64")]},
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


class TestDescribeImage:
    url = "/v3/images/custom/{image_name}"
    method = "GET"

    def _send_test_request(self, client, image_name, region="us-east-1"):
        query_string = []
        if region:
            query_string.append(("region", region))
        headers = {"Accept": "application/json"}
        return client.open(
            self.url.format(image_name=image_name), method=self.method, headers=headers, query_string=query_string
        )

    def test_describe_of_image_already_available(self, client, mocker):
        mocker.patch("pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag", return_value=_create_image_info("image1"))
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack_resource", return_value=None)
        mocker.patch(
            "pcluster.api.controllers.image_operations_controller._presigned_config_url",
            return_value="https://parallelcluster.aws.com/bucket/key",
        )

        expected_response = {
            "creationTime": to_iso_timestr(datetime(2021, 4, 12)),
            "ec2AmiInfo": {
                "amiId": "image1",
                "amiName": "image1",
                "architecture": "x86_64",
                "state": Ec2AmiState.AVAILABLE,
                "description": "description",
                "tags": [
                    {"key": "parallelcluster:image_id", "value": "image1"},
                    {"key": "parallelcluster:version", "value": "3.0.0"},
                    {"key": "parallelcluster:build_config", "value": "s3://bucket/key"},
                ],
            },
            "imageBuildStatus": ImageBuildStatus.BUILD_COMPLETE,
            "imageConfiguration": {"url": "https://parallelcluster.aws.com/bucket/key"},
            "imageId": "image1",
            "region": "us-east-1",
            "version": "3.0.0",
        }

        response = self._send_test_request(client, "image1")

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            assert_that(response.get_json()).is_equal_to(expected_response)

    def test_describe_of_image_not_yet_available_with_no_associated_imagebuilder_image(self, client, mocker):
        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag",
            side_effect=ImageNotFoundError("describe_image_by_id_tag"),
        )
        mocker.patch(
            "pcluster.aws.cfn.CfnClient.describe_stack",
            return_value=_create_stack("image1", CloudFormationStackStatus.CREATE_IN_PROGRESS),
        )
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack_resource", return_value=None)
        mocker.patch(
            "pcluster.api.controllers.image_operations_controller._presigned_config_url",
            return_value="https://parallelcluster.aws.com/bucket/key",
        )

        expected_response = {
            "imageConfiguration": {"url": "https://parallelcluster.aws.com/bucket/key"},
            "imageId": "image1",
            "imageBuildStatus": ImageBuildStatus.BUILD_IN_PROGRESS,
            "cloudformationStackStatus": CloudFormationStackStatus.CREATE_IN_PROGRESS,
            "cloudformationStackArn": "arn:image1",
            "imageBuildLogsArn": "arn:image1:build_log",
            "cloudformationStackCreationTime": to_iso_timestr(datetime(2021, 4, 12)),
            "cloudformationStackTags": [
                {"key": "parallelcluster:image_id", "value": "image1"},
                {"key": "parallelcluster:version", "value": "3.0.0"},
                {"key": "parallelcluster:build_config", "value": "s3://bucket/key"},
                {"key": "parallelcluster:build_log", "value": "arn:image1:build_log"},
            ],
            "region": "us-east-1",
            "version": "3.0.0",
        }

        response = self._send_test_request(client, "image1")

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            assert_that(response.get_json()).is_equal_to(expected_response)

    def test_describe_image_in_failed_state_with_reasons_and_associated_imagebuilder_image(self, client, mocker):
        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag",
            side_effect=ImageNotFoundError("describe_image_by_id_tag"),
        )
        mocker.patch(
            "pcluster.aws.cfn.CfnClient.describe_stack",
            return_value=_create_stack("image1", CloudFormationStackStatus.CREATE_FAILED, "cfn test reason"),
        )
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack_resource", return_value=None)
        mocker.patch(
            "pcluster.aws.cfn.CfnClient.describe_stack_resource",
            return_value={"StackResourceDetail": {"PhysicalResourceId": "test_id"}},
        )
        mocker.patch(
            "pcluster.aws.imagebuilder.ImageBuilderClient.get_image_state",
            return_value={"status": ImageBuilderImageStatus.FAILED, "reason": "img test reason"},
        )
        mocker.patch(
            "pcluster.api.controllers.image_operations_controller._presigned_config_url",
            return_value="https://parallelcluster.aws.com/bucket/key",
        )

        expected_response = {
            "cloudformationStackArn": "arn:image1",
            "imageBuildLogsArn": "arn:image1:build_log",
            "cloudformationStackCreationTime": to_iso_timestr(to_utc_datetime("2021-04-12 00:00:00")),
            "cloudformationStackTags": [
                {"key": "parallelcluster:image_id", "value": "image1"},
                {"key": "parallelcluster:version", "value": "3.0.0"},
                {"key": "parallelcluster:build_config", "value": "s3://bucket/key"},
                {"key": "parallelcluster:build_log", "value": "arn:image1:build_log"},
            ],
            "cloudformationStackStatus": CloudFormationStackStatus.CREATE_FAILED,
            "cloudformationStackStatusReason": "cfn test reason",
            "imageBuildStatus": ImageBuildStatus.BUILD_FAILED,
            "imageConfiguration": {"url": "https://parallelcluster.aws.com/bucket/key"},
            "imageId": "image1",
            "imagebuilderImageStatus": ImageBuilderImageStatus.FAILED,
            "imagebuilderImageStatusReason": "img test reason",
            "region": "us-east-1",
            "version": "3.0.0",
        }

        response = self._send_test_request(client, "image1")

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize(
        "method_to_patch, error, error_code",
        [
            ("pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag", LimitExceededError, 429),
            ("pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag", BadRequestError, 400),
            ("pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag", AWSClientError, 500),
            ("pcluster.aws.cfn.CfnClient.describe_stack", LimitExceededError, 429),
            ("pcluster.aws.cfn.CfnClient.describe_stack", BadRequestError, 400),
            ("pcluster.aws.cfn.CfnClient.describe_stack", AWSClientError, 500),
            ("pcluster.aws.cfn.CfnClient.describe_stack", StackNotFoundError, 404),
        ],
    )
    def test_that_errors_are_converted(self, client, mocker, method_to_patch, error, error_code):
        method = method_to_patch.split(".")[-1]
        if method == "describe_stack":
            mocker.patch(
                "pcluster.aws.ec2.Ec2Client.describe_image_by_id_tag",
                side_effect=ImageNotFoundError("describe_image_by_id_tag"),
            )
        mocker.patch(method_to_patch, side_effect=error(method, "test error"))

        if error == StackNotFoundError:
            expected_error = {"message": "No image or stack associated with ParallelCluster image id: image1."}
        elif error == BadRequestError:
            expected_error = {"message": "Bad Request: Unable to get image image1, due to test error."}
        else:
            expected_error = {"message": "Unable to get image image1, due to test error."}

        response = self._send_test_request(client, "image1")

        with soft_assertions():
            assert_that(response.status_code).is_equal_to(error_code)
            assert_that(response.get_json()).is_equal_to(expected_error)

    def test_unsupported_operation_error(self, client, mocker):
        mocked_assert_supported_operation = mock_assert_supported_operation(
            mocker, "pcluster.api.controllers.image_operations_controller.assert_supported_operation"
        )
        response = self._send_test_request(client, "image1")
        verify_unsupported_operation(
            mocked_assertion=mocked_assert_supported_operation,
            operation=Operation.DESCRIBE_IMAGE,
            region="us-east-1",
            response=response,
        )
