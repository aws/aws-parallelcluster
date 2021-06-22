# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import pytest
from assertpy import assert_that

from pcluster.aws.common import AWSClientError
from pcluster.models.imagebuilder import ImageBuilderStack
from tests.pcluster.aws.dummy_aws_api import mock_aws_api


class TestImageBuilderStack:
    @pytest.mark.parametrize(
        "describe_stack_resouces_result, expected_error, expected_imagebuilder_image_is_building",
        [
            (
                {
                    "StackResourceDetail": {
                        "ResourceStatus": "BUILD_COMPLETE",
                    }
                },
                False,
                False,
            ),
            (
                {
                    "StackResourceDetail": {
                        "ResourceStatus": "CREATE_IN_PROGRESS",
                    }
                },
                False,
                True,
            ),
            (AWSClientError(function_name="describe_stack_resource", message="test error"), True, False),
        ],
    )
    def test_initialization(
        self, mocker, describe_stack_resouces_result, expected_error, expected_imagebuilder_image_is_building
    ):
        mock_aws_api(mocker)
        if expected_error:
            mocker.patch(
                "pcluster.aws.cfn.CfnClient.describe_stack_resource", side_effect=describe_stack_resouces_result
            )
            stack = ImageBuilderStack({})
            assert_that(stack._imagebuilder_image_resource).is_none()
        else:
            mocker.patch(
                "pcluster.aws.cfn.CfnClient.describe_stack_resource", return_value=describe_stack_resouces_result
            )
            stack = ImageBuilderStack({})
            assert_that(stack._imagebuilder_image_resource).is_equal_to(describe_stack_resouces_result)

        assert_that(stack.imagebuilder_image_is_building).is_equal_to(expected_imagebuilder_image_is_building)
