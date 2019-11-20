"""This module provides unit tests for the functions in the pcluster.utils module."""

import json

import pytest

import pcluster.utils as utils
from assertpy import assert_that
from tests.common import MockedBoto3Request

FAKE_CLUSTER_NAME = "cluster_name"
FAKE_STACK_NAME = utils.get_stack_name(FAKE_CLUSTER_NAME)
STACK_TYPE = "AWS::CloudFormation::Stack"


@pytest.fixture()
def boto3_stubber_path():
    """Specify that boto3_mocker should stub calls to boto3 for the pcluster.utils module."""
    return "pcluster.utils.boto3"


def test_get_stack_name():
    """Test utils.get_stack_name."""
    expected_stack_name = "parallelcluster-{0}".format(FAKE_CLUSTER_NAME)
    assert_that(utils.get_stack_name(FAKE_CLUSTER_NAME)).is_equal_to(expected_stack_name)


@pytest.mark.parametrize(
    "template_body,error_message",
    [
        ({"TemplateKey": "TemplateValue"}, None),
        ({}, "Unable to get template for stack {0}.$".format(FAKE_STACK_NAME)),
        (None, "Unable to get template for stack {0}\n.+".format(FAKE_STACK_NAME)),
    ],
)
def test_get_stack_template(boto3_stubber, template_body, error_message):
    """Verify that utils.get_stack_template behaves as expected."""
    response = {"TemplateBody": json.dumps(template_body)} if template_body is not None else error_message
    mocked_requests = [
        MockedBoto3Request(method="get_template", response=response, expected_params={"StackName": FAKE_STACK_NAME})
    ]
    generate_errors = template_body is None
    boto3_stubber("cloudformation", mocked_requests, generate_errors=generate_errors)
    if error_message is not None:
        with pytest.raises(SystemExit, match=error_message) as sysexit:
            utils.get_stack_template(stack_name=FAKE_STACK_NAME)
        assert_that(sysexit.value.code).is_not_equal_to(0)
    else:
        assert_that(utils.get_stack_template(stack_name=FAKE_STACK_NAME)).is_equal_to(response.get("TemplateBody"))


@pytest.mark.parametrize(
    "error_message",
    [
        None,
        "No UpDatES ARE TO BE PERformed",
        "no updates are to be performed",
        "NO UPDATES ARE TO BE PERFORMED",
        "some longer message also containing no updates are to be performed and more words at the end"
        "some other error message",
    ],
)
def test_update_stack_template(boto3_stubber, error_message):
    """Verify that utils.update_stack_template behaves as expected."""
    template_body = {"TemplateKey": "TemplateValue"}
    cfn_params = [{"ParameterKey": "Key", "ParameterValue": "Value"}]
    expected_params = {
        "StackName": FAKE_STACK_NAME,
        "TemplateBody": json.dumps(template_body, indent=2),
        "Parameters": cfn_params,
    }
    response = error_message if error_message is not None else {"StackId": "stack ID"}
    mocked_requests = [MockedBoto3Request(method="update_stack", response=response, expected_params=expected_params)]
    generate_errors = error_message is not None
    boto3_stubber("cloudformation", mocked_requests, generate_errors=generate_errors)
    if error_message is None or "no updates are to be performed" in error_message.lower():
        utils.update_stack_template(FAKE_STACK_NAME, template_body, cfn_params)
    else:
        full_error_message = "Unable to update stack template for stack {stack_name}: {emsg}".format(
            stack_name=FAKE_STACK_NAME, emsg=error_message
        )
        with pytest.raises(SystemExit, match=full_error_message) as sysexit:
            utils.update_stack_template(FAKE_STACK_NAME, template_body, cfn_params)
        assert_that(sysexit.value.code).is_not_equal_to(0)


@pytest.mark.parametrize(
    "resources",
    [
        [
            {"ResourceType": "Not a stack", "ResourceName": "name_one"},
            {"ResourceType": STACK_TYPE, "ResourceName": "name_two"},
            {"ResourceType": "Also not a stack", "ResourceName": "name_three"},
            {"ResourceType": STACK_TYPE, "ResourceName": "name_four"},
        ],
        [],
    ],
)
def test_get_cluster_substacks(mocker, resources):
    """Verify that utils.get_cluster_substacks behaves as expected."""
    mocker.patch("pcluster.utils.get_stack_resources").return_value = resources
    expected_substacks = [r for r in resources if r.get("ResourceType") == STACK_TYPE]
    observed_substacks = utils.get_cluster_substacks(FAKE_CLUSTER_NAME)
    utils.get_stack_resources.assert_called_with(FAKE_STACK_NAME)
    assert_that(observed_substacks).is_equal_to(expected_substacks)


@pytest.mark.parametrize(
    "substacks_response,expected,error_message",
    [
        (
            [
                {"StackName": "substack_one"},
                {"StackName": "substack_two"},
                {"StackName": "not_a_substack"},
                {"StackName": "{0}-CloudWatchLogsSubstack-skdfjaldks".format(utils.get_stack_name(FAKE_CLUSTER_NAME))},
            ],
            {"StackName": "{0}-CloudWatchLogsSubstack-skdfjaldks".format(utils.get_stack_name(FAKE_CLUSTER_NAME))},
            None,
        ),
        (
            [{"StackName": "substack_one"}, {"StackName": "substack_two"}, {"StackName": "not_a_substack"}],
            None,
            "Unable to get CloudWatch logs substack for cluster {0}".format(FAKE_CLUSTER_NAME),
        ),
    ],
)
def test_get_cloudwatch_logs_substack(mocker, substacks_response, expected, error_message):
    """Verify that utils.get_cloudwatch_logs_substack behaves as expected."""
    mocker.patch("pcluster.utils.get_cluster_substacks").return_value = substacks_response
    if error_message is None:
        assert_that(utils.get_cloudwatch_logs_substack(FAKE_CLUSTER_NAME)).is_equal_to(expected)
    else:
        with pytest.raises(SystemExit, match=error_message) as sysexit:
            utils.get_cloudwatch_logs_substack(FAKE_CLUSTER_NAME)
        assert_that(sysexit.value.code).is_not_equal_to(0)
    utils.get_cluster_substacks.assert_called_with(FAKE_CLUSTER_NAME)


@pytest.mark.parametrize(
    "response,is_error",
    [
        ("Stack with id {0} does not exist".format(FAKE_STACK_NAME), True),
        ({"Stacks": [{"StackName": FAKE_STACK_NAME, "CreationTime": 0, "StackStatus": "CREATED"}]}, False),
    ],
)
def test_stack_exists(boto3_stubber, response, is_error):
    """Verify that utils.stack_exists behaves as expected."""
    mocked_requests = [
        MockedBoto3Request(method="describe_stacks", response=response, expected_params={"StackName": FAKE_STACK_NAME},)
    ]
    boto3_stubber("cloudformation", mocked_requests, generate_errors=is_error)
    should_exist = not is_error
    assert_that(utils.stack_exists(FAKE_STACK_NAME)).is_equal_to(should_exist)


@pytest.mark.parametrize(
    "resources,error_message",
    [
        (
            [
                {
                    "StackName": FAKE_STACK_NAME,
                    "StackId": "stack_id",
                    "LogicalResourceId": "logical_resource_id",
                    "ResourceType": "resource_type",
                    "Timestamp": 0,
                    "ResourceStatus": "resource_status",
                },
            ],
            None,
        ),
        (None, "Some error message"),
    ],
)
def test_get_stack_resources(boto3_stubber, resources, error_message):
    """Verify that utils.get_stack_resources behaves as expected."""
    if error_message is None:
        response = {"StackResources": resources}
    else:
        response = "Unable to get {stack_name}'s resources: {error_message}".format(
            stack_name=FAKE_STACK_NAME, error_message=error_message
        )
    mocked_requests = [
        MockedBoto3Request(
            method="describe_stack_resources", response=response, expected_params={"StackName": FAKE_STACK_NAME}
        )
    ]
    generate_errors = error_message is not None
    boto3_stubber("cloudformation", mocked_requests, generate_errors=generate_errors)
    if error_message is None:
        assert_that(utils.get_stack_resources(FAKE_STACK_NAME)).is_equal_to(resources)
    else:
        with pytest.raises(SystemExit, match=response) as sysexit:
            utils.get_stack_resources(FAKE_STACK_NAME)
        assert_that(sysexit.value.code).is_not_equal_to(0)
