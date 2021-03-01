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
from tests.common.dummy_aws_api import DummyAWSApi

FAKE_STACK_NAME = "parallelcluster-name"


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

    cluster_stack = ClusterStack({"StackName": FAKE_STACK_NAME})
    if error_message:
        with pytest.raises(ClusterActionError, match=error_message):
            _ = cluster_stack.template
    else:
        assert_that(cluster_stack.template).is_equal_to(response)


@pytest.mark.parametrize(
    "stack_statuses",
    [
        ["UPDATE_IN_PROGRESS", "UPDATE_IN_PROGRESS", "UPDATE_IN_PROGRESS", "UPDATE_COMPLETE"],
        ["UPDATE_IN_PROGRESS", "UPDATE_IN_PROGRESS", "UPDATE_IN_PROGRESS", "anything other than UPDATE_IN_PROGRESS"],
        ["UPDATE_COMPLETE"],
    ],
)
def test_wait_for_stack_update(mocker, stack_statuses):
    """
    Verify that ClusterStack._wait_for_update behaves as expected.

    _wait_for_update should call updated_status until the StackStatus is anything besides UPDATE_IN_PROGRESS,
    use that to get expected call count for updated_status
    """
    expected_call_count = 0
    for status_idx, status in enumerate(stack_statuses):
        if status != "UPDATE_IN_PROGRESS":
            expected_call_count = status_idx + 1
            break

    cluster_stack = ClusterStack({"StackName": FAKE_STACK_NAME})

    updated_status_mock = mocker.patch.object(cluster_stack, "updated_status", side_effect=stack_statuses)
    mocker.patch("pcluster.models.cluster.time.sleep")  # so we don't actually have to wait

    cluster_stack._wait_for_update()
    assert_that(updated_status_mock.call_count).is_equal_to(expected_call_count)


@pytest.mark.parametrize(
    "error_message",
    [
        None,
        "No UpDatES ARE TO BE PERformed",
        "some longer message also containing no updates are to be performed and more words at the end"
        "some other error message",
    ],
)
def test_update_stack_template(mocker, error_message):
    """Verify that utils.update_stack_template behaves as expected."""
    template_body = {"TemplateKey": "TemplateValue"}
    cfn_params = [{"ParameterKey": "Key", "ParameterValue": "Value"}]
    response = error_message or {"StackId": "stack ID"}

    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch("common.boto3.cfn.CfnClient.get_stack_template", return_value=template_body)
    mocker.patch(
        "common.boto3.cfn.CfnClient.update_stack",
        return_value=response,
        expected_params={
            "stack_name": FAKE_STACK_NAME,
            "updated_template": json.dumps(template_body, indent=2),
            "params": cfn_params,
        },
        side_effect=AWSClientError(function_name="update_stack", message=error_message)
        if error_message is not None
        else None,
    )

    cluster_stack = ClusterStack({"StackName": FAKE_STACK_NAME})
    wait_for_update_mock = mocker.patch.object(cluster_stack, "_wait_for_update")

    if error_message is None or "no updates are to be performed" in error_message.lower():
        cluster_stack._update_template()
        if error_message is None or "no updates are to be performed" not in error_message.lower():
            assert_that(wait_for_update_mock.called).is_true()
        else:
            assert_that(wait_for_update_mock.called).is_false()
    else:
        full_error_message = "Unable to update stack template for stack {stack_name}: {emsg}".format(
            stack_name=FAKE_STACK_NAME, emsg=error_message
        )
        with pytest.raises(AWSClientError, match=full_error_message) as sysexit:
            cluster_stack._update_template()
        assert_that(sysexit.value.code).is_not_equal_to(0)
