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

from common import imagebuilder_utils


@pytest.mark.parametrize(
    "parent_image, response, ami_id",
    [
        (
            "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
            {"image": {"outputResources": {"amis": [{"image": "ami-0be2609ba883822ec"}]}}},
            "ami-0be2609ba883822ec",
        ),
        ("ami-00e87074e52e6c9f9", "{}", "ami-00e87074e52e6c9f9"),
    ],
)
def test_evaluate_ami_id(mocker, parent_image, response, ami_id):
    mocker.patch("common.imagebuilder_utils.ImageBuilderClient.__init__", return_value=None)
    mocker.patch("common.imagebuilder_utils.ImageBuilderClient.get_image_resources", return_value=response)
    assert_that(imagebuilder_utils.get_ami_id(parent_image)).is_equal_to(ami_id)


@pytest.mark.parametrize(
    "image_arn, response",
    [
        (
            "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/2020.12.21",
            {"requestId": "abcd", "image": {"outputResources": {"amis": [{"image": "ami-0be2609ba883822ec"}]}}},
        ),
        (
            "arn:aws-fake:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86",
            "Some error message",
        ),
    ],
)
def test_get_info_for_ami_from_arn(mocker, image_arn, response):
    """Verify get_info_for_ami_from_arn returns the expected response, and that errors cause nonzero exit."""
    mocker.patch("common.imagebuilder_utils.ImageBuilderClient.__init__", return_value=None)
    mocker.patch("common.imagebuilder_utils.ImageBuilderClient.get_image_resources", return_value=response)
    assert_that(imagebuilder_utils.get_info_for_ami_from_arn(image_arn)).is_equal_to(response)
