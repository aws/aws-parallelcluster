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
#
# This module contains all the classes representing the Resources objects.
# These objects are obtained from the configuration file through a conversion based on the Schema classes.
#
import json

import pytest
from assertpy import assert_that

from common.boto3.common import AWSClientError
from pcluster.models.cluster import ClusterActionError, ClusterStack
from tests.pcluster.boto3.dummy_boto3 import DummyAWSApi
from tests.pcluster.test_utils import FAKE_STACK_NAME


@pytest.mark.parametrize(
    "template_body,error_message",
    [
        ({"TemplateKey": "TemplateValue"}, None),
        ({}, "Unable to retrieve template for stack {0}.*".format(FAKE_STACK_NAME)),
        (None, "Unable to retrieve template for stack {0}.*".format(FAKE_STACK_NAME)),
    ],
)
def test_get_stack_template(mocker, template_body, error_message):
    """Verify that ClusterStack template property behaves as expected."""
    response = json.dumps(template_body) if template_body is not None else error_message
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch(
        "common.boto3.cfn.CfnClient.get_stack_template",
        return_value=response,
        expected_params=FAKE_STACK_NAME,
        side_effect=AWSClientError(function_name="get_template", message="error") if not template_body else None,
    )

    cluster_stack = ClusterStack(FAKE_STACK_NAME, {})
    if error_message:
        with pytest.raises(ClusterActionError, match=error_message):
            _ = cluster_stack.template
    else:
        assert_that(cluster_stack.template).is_equal_to(response)
