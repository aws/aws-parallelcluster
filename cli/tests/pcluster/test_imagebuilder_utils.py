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

from pcluster import imagebuilder_utils
from tests.pcluster.aws.dummy_aws_api import mock_aws_api


@pytest.mark.parametrize(
    "parent_image, response, ami_id",
    [
        (
            "arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x",
            "ami-0be2609ba883822ec",
            "ami-0be2609ba883822ec",
        ),
        ("ami-00e87074e52e6c9f9", "{}", "ami-00e87074e52e6c9f9"),
    ],
)
def test_evaluate_ami_id(mocker, parent_image, response, ami_id):
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.imagebuilder.ImageBuilderClient.get_image_id", return_value=response)
    assert_that(imagebuilder_utils.get_ami_id(parent_image)).is_equal_to(ami_id)
