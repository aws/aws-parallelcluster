"""This module provides unit tests for the functions in the pcluster.utils module."""

import json

import pytest
from botocore.exceptions import ClientError

import pcluster.utils as utils
from assertpy import assert_that
from pcluster.utils import get_bucket_url
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
        MockedBoto3Request(
            method="get_template",
            response=response,
            expected_params={"StackName": FAKE_STACK_NAME},
            generate_error=template_body is None,
        )
    ]
    boto3_stubber("cloudformation", mocked_requests)
    if error_message:
        with pytest.raises(SystemExit, match=error_message) as sysexit:
            utils.get_stack_template(stack_name=FAKE_STACK_NAME)
        assert_that(sysexit.value.code).is_not_equal_to(0)
    else:
        assert_that(utils.get_stack_template(stack_name=FAKE_STACK_NAME)).is_equal_to(response.get("TemplateBody"))


@pytest.mark.parametrize(
    "stack_statuses",
    [
        ["UPDATE_IN_PROGRESS", "UPDATE_IN_PROGRESS", "UPDATE_IN_PROGRESS", "UPDATE_COMPLETE"],
        ["UPDATE_IN_PROGRESS", "UPDATE_IN_PROGRESS", "UPDATE_IN_PROGRESS", "anything other than UPDATE_IN_PROGRESS"],
        ["UPDATE_COMPLETE"],
    ],
)
def test_wait_for_stack_update(mocker, stack_statuses):
    """Verify that utils._wait_for_update behaves as expected."""
    get_stack_returns = [{"StackStatus": s} for s in stack_statuses]

    # _wait_for_update should call utils.get_stack until the StackStatus is anything besides UPDATE_IN_PROGRESS,
    # use that to get expected call count for utils.get_stack
    expected_call_count = 0
    for status_idx, status in enumerate(stack_statuses):
        if status != "UPDATE_IN_PROGRESS":
            expected_call_count = status_idx + 1
            break

    mocker.patch("pcluster.utils.get_stack").side_effect = get_stack_returns
    mocker.patch("pcluster.utils.time.sleep")  # so we don't actually have to wait
    utils._wait_for_update(FAKE_STACK_NAME)
    utils.get_stack.assert_called_with(FAKE_STACK_NAME)
    assert_that(utils.get_stack.call_count).is_equal_to(expected_call_count)


@pytest.mark.parametrize(
    "error_message",
    [
        None,
        "No UpDatES ARE TO BE PERformed",
        "some longer message also containing no updates are to be performed and more words at the end"
        "some other error message",
    ],
)
def test_update_stack_template(mocker, boto3_stubber, error_message):
    """Verify that utils.update_stack_template behaves as expected."""
    template_body = {"TemplateKey": "TemplateValue"}
    cfn_params = [{"ParameterKey": "Key", "ParameterValue": "Value"}]
    expected_params = {
        "StackName": FAKE_STACK_NAME,
        "TemplateBody": json.dumps(template_body, indent=2),
        "Parameters": cfn_params,
        "Capabilities": ["CAPABILITY_IAM"],
    }
    response = error_message or {"StackId": "stack ID"}
    mocked_requests = [
        MockedBoto3Request(
            method="update_stack",
            response=response,
            expected_params=expected_params,
            generate_error=error_message is not None,
        )
    ]
    boto3_stubber("cloudformation", mocked_requests)
    mocker.patch("pcluster.utils._wait_for_update")
    if error_message is None or "no updates are to be performed" in error_message.lower():
        utils.update_stack_template(FAKE_STACK_NAME, template_body, cfn_params)
        if error_message is None or "no updates are to be performed" not in error_message.lower():
            utils._wait_for_update.assert_called_with(FAKE_STACK_NAME)
        else:
            assert_that(utils._wait_for_update.called).is_false()
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
            {"ResourceType": "Not a stack", "ResourceName": "name_one", "PhysicalResourceId": "PhysIdOne"},
            {"ResourceType": STACK_TYPE, "ResourceName": "name_two", "PhysicalResourceId": "PhysIdTwo"},
            {"ResourceType": "Also not a stack", "ResourceName": "name_three", "PhysicalResourceId": "PhysIdThree"},
            {"ResourceType": STACK_TYPE, "ResourceName": "name_four", "PhysicalResourceId": "PhysIdFour"},
        ],
        [],
    ],
)
def test_get_cluster_substacks(mocker, resources):  # noqa: D202
    """Verify that utils.get_cluster_substacks behaves as expected."""

    def fake_get_stack(phys_id):
        return phys_id

    mocker.patch("pcluster.utils.get_stack_resources").return_value = resources
    mocker.patch("pcluster.utils.get_stack").side_effect = fake_get_stack
    expected_substacks = [
        fake_get_stack(r.get("PhysicalResourceId")) for r in resources if r.get("ResourceType") == STACK_TYPE
    ]
    observed_substacks = utils.get_cluster_substacks(FAKE_CLUSTER_NAME)
    utils.get_stack_resources.assert_called_with(FAKE_STACK_NAME)
    assert_that(observed_substacks).is_equal_to(expected_substacks)


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
        MockedBoto3Request(
            method="describe_stacks",
            response=response,
            expected_params={"StackName": FAKE_STACK_NAME},
            generate_error=is_error,
        )
    ]
    boto3_stubber("cloudformation", mocked_requests)
    should_exist = not is_error
    assert_that(utils.stack_exists(FAKE_STACK_NAME)).is_equal_to(should_exist)


@pytest.mark.parametrize(
    "resources, error_message",
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
                }
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
            method="describe_stack_resources",
            response=response,
            expected_params={"StackName": FAKE_STACK_NAME},
            generate_error=error_message is not None,
        )
    ]
    boto3_stubber("cloudformation", mocked_requests)
    if error_message is None:
        assert_that(utils.get_stack_resources(FAKE_STACK_NAME)).is_equal_to(resources)
    else:
        with pytest.raises(SystemExit, match=response) as sysexit:
            utils.get_stack_resources(FAKE_STACK_NAME)
        assert_that(sysexit.value.code).is_not_equal_to(0)


def test_retry_on_boto3_throttling(boto3_stubber, mocker):
    sleep_mock = mocker.patch("pcluster.utils.time.sleep")
    mocked_requests = [
        MockedBoto3Request(
            method="describe_stack_resources",
            response="Error",
            expected_params={"StackName": FAKE_STACK_NAME},
            generate_error=True,
            error_code="Throttling",
        ),
        MockedBoto3Request(
            method="describe_stack_resources",
            response="Error",
            expected_params={"StackName": FAKE_STACK_NAME},
            generate_error=True,
            error_code="Throttling",
        ),
        MockedBoto3Request(
            method="describe_stack_resources", response={}, expected_params={"StackName": FAKE_STACK_NAME}
        ),
    ]
    client = boto3_stubber("cloudformation", mocked_requests)
    utils.retry_on_boto3_throttling(client.describe_stack_resources, StackName=FAKE_STACK_NAME)
    sleep_mock.assert_called_with(5)


def test_get_stack_resources_retry(boto3_stubber, mocker):
    sleep_mock = mocker.patch("pcluster.utils.time.sleep")
    mocked_requests = [
        MockedBoto3Request(
            method="describe_stack_resources",
            response="Error",
            expected_params={"StackName": FAKE_STACK_NAME},
            generate_error=True,
            error_code="Throttling",
        ),
        MockedBoto3Request(
            method="describe_stack_resources", response={}, expected_params={"StackName": FAKE_STACK_NAME}
        ),
    ]
    boto3_stubber("cloudformation", mocked_requests)
    utils.get_stack_resources(FAKE_STACK_NAME)
    sleep_mock.assert_called_with(5)


def test_get_stack_retry(boto3_stubber, mocker):
    sleep_mock = mocker.patch("pcluster.utils.time.sleep")
    expected_stack = {"StackName": FAKE_STACK_NAME, "CreationTime": 0, "StackStatus": "CREATED"}
    mocked_requests = [
        MockedBoto3Request(
            method="describe_stacks",
            response="Error",
            expected_params={"StackName": FAKE_STACK_NAME},
            generate_error=True,
            error_code="Throttling",
        ),
        MockedBoto3Request(
            method="describe_stacks",
            response={"Stacks": [expected_stack]},
            expected_params={"StackName": FAKE_STACK_NAME},
        ),
    ]
    boto3_stubber("cloudformation", mocked_requests)
    stack = utils.get_stack(FAKE_STACK_NAME)
    assert_that(stack).is_equal_to(expected_stack)
    sleep_mock.assert_called_with(5)


def test_verify_stack_creation_retry(boto3_stubber, mocker):
    sleep_mock = mocker.patch("pcluster.utils.time.sleep")
    mocker.patch(
        "pcluster.utils.get_stack",
        side_effect=[{"StackStatus": "CREATE_IN_PROGRESS"}, {"StackStatus": "CREATE_FAILED"}],
    )
    mocked_requests = [
        MockedBoto3Request(
            method="describe_stack_events",
            response="Error",
            expected_params={"StackName": FAKE_STACK_NAME},
            generate_error=True,
            error_code="Throttling",
        ),
        MockedBoto3Request(
            method="describe_stack_events",
            response={"StackEvents": [_generate_stack_event()]},
            expected_params={"StackName": FAKE_STACK_NAME},
        ),
    ]
    client = boto3_stubber("cloudformation", mocked_requests * 2)
    assert_that(utils.verify_stack_creation(FAKE_STACK_NAME, client)).is_false()
    sleep_mock.assert_called_with(5)


def test_get_stack_events_retry(boto3_stubber, mocker):
    sleep_mock = mocker.patch("pcluster.utils.time.sleep")
    expected_events = [_generate_stack_event()]
    mocked_requests = [
        MockedBoto3Request(
            method="describe_stack_events",
            response="Error",
            expected_params={"StackName": FAKE_STACK_NAME},
            generate_error=True,
            error_code="Throttling",
        ),
        MockedBoto3Request(
            method="describe_stack_events",
            response={"StackEvents": expected_events},
            expected_params={"StackName": FAKE_STACK_NAME},
        ),
    ]
    boto3_stubber("cloudformation", mocked_requests)
    assert_that(utils.get_stack_events(FAKE_STACK_NAME)).is_equal_to(expected_events)
    sleep_mock.assert_called_with(5)


def _generate_stack_event():
    return {
        "LogicalResourceId": "id",
        "ResourceStatus": "status",
        "StackId": "id",
        "EventId": "id",
        "StackName": FAKE_STACK_NAME,
        "Timestamp": 0,
    }


@pytest.mark.parametrize(
    "bucket_prefix", ["test", "test-", "prefix-63-characters-long--------------------------------to-cut"]
)
def test_generate_random_bucket_name(bucket_prefix):
    bucket_name = utils.generate_random_bucket_name(bucket_prefix)
    max_bucket_name_length = 63
    random_suffix_length = 17  # 16 digits + 1 separator

    pruned_prefix = bucket_prefix[: max_bucket_name_length - len(bucket_prefix) - random_suffix_length]
    assert_that(bucket_name).starts_with(pruned_prefix)
    assert_that(len(bucket_name)).is_equal_to(len(pruned_prefix) + random_suffix_length)

    # Verify bucket name limits: bucket name must be at least 3 and no more than 63 characters long
    assert_that(len(bucket_name)).is_between(3, max_bucket_name_length)


@pytest.mark.parametrize(
    "region,error_message", [("eu-west-1", None), ("us-east-1", None), ("eu-west-1", "An error occurred")]
)
def test_create_s3_bucket(region, error_message, boto3_stubber):
    bucket_name = "test"
    expected_params = {"Bucket": bucket_name}
    if region != "us-east-1":
        # LocationConstraint specifies the region where the bucket will be created.
        # When the region is us-east-1 we are not specifying this parameter because it's the default region.
        expected_params["CreateBucketConfiguration"] = {"LocationConstraint": region}

    mocked_requests = [
        MockedBoto3Request(
            method="create_bucket",
            expected_params=expected_params,
            response={"Location": bucket_name},
            generate_error=error_message is not None,
        )
    ]

    boto3_stubber("s3", mocked_requests)
    if error_message:
        with pytest.raises(ClientError, match=error_message):
            utils.create_s3_bucket(bucket_name, region)
    else:
        utils.create_s3_bucket(bucket_name, region)


@pytest.mark.parametrize(
    "node_type, expected_fallback, expected_response, expected_instances",
    [
        (utils.NodeType.master, False, {"Reservations": [{"Groups": [], "Instances": [{}]}]}, 1),
        (utils.NodeType.master, True, {"Reservations": [{"Groups": [], "Instances": [{}]}]}, 1),
        (utils.NodeType.master, True, {"Reservations": []}, 0),
        (utils.NodeType.compute, False, {"Reservations": [{"Groups": [], "Instances": [{}, {}, {}]}]}, 3),
        (utils.NodeType.compute, True, {"Reservations": [{"Groups": [], "Instances": [{}, {}]}]}, 2),
        (utils.NodeType.compute, True, {"Reservations": []}, 0),
    ],
)
def test_describe_cluster_instances(boto3_stubber, node_type, expected_fallback, expected_response, expected_instances):
    mocked_requests = [
        MockedBoto3Request(
            method="describe_instances",
            expected_params={
                "Filters": [
                    {"Name": "tag:Application", "Values": ["test-cluster"]},
                    {"Name": "instance-state-name", "Values": ["running"]},
                    {"Name": "tag:aws-parallelcluster-node-type", "Values": [str(node_type)]},
                ]
            },
            response=expected_response if not expected_fallback else {"Reservations": []},
        )
    ]
    if expected_fallback:
        mocked_requests.append(
            MockedBoto3Request(
                method="describe_instances",
                expected_params={
                    "Filters": [
                        {"Name": "tag:Application", "Values": ["test-cluster"]},
                        {"Name": "instance-state-name", "Values": ["running"]},
                        {"Name": "tag:Name", "Values": [str(node_type)]},
                    ]
                },
                response=expected_response,
            )
        )
    boto3_stubber("ec2", mocked_requests)
    instances = utils.describe_cluster_instances("test-cluster", node_type=node_type)
    assert_that(instances).is_length(expected_instances)


@pytest.mark.parametrize(
    "master_instance, expected_ip, error",
    [
        (
            {
                "PrivateIpAddress": "10.0.16.17",
                "PublicIpAddress": "18.188.93.193",
                "State": {"Code": 16, "Name": "running"},
            },
            "18.188.93.193",
            None,
        ),
        ({"PrivateIpAddress": "10.0.16.17", "State": {"Code": 16, "Name": "running"}}, "10.0.16.17", None),
        (
            {
                "PrivateIpAddress": "10.0.16.17",
                "PublicIpAddress": "18.188.93.193",
                "State": {"Code": 16, "Name": "stopped"},
            },
            "18.188.93.193",
            "MasterServer: STOPPED",
        ),
    ],
    ids=["public_ip", "private_ip", "stopped"],
)
def test_get_master_server_ips(mocker, master_instance, expected_ip, error):
    describe_cluster_instances_mock = mocker.patch(
        "pcluster.utils.describe_cluster_instances", return_value=[master_instance]
    )

    if error:
        with pytest.raises(SystemExit, match=error):
            utils._get_master_server_ip("stack-name")
    else:
        assert_that(utils._get_master_server_ip("stack-name")).is_equal_to(expected_ip)
        describe_cluster_instances_mock.assert_called_with("stack-name", node_type=utils.NodeType.master)


@pytest.mark.parametrize(
    "region, expected_url",
    [
        ("us-east-1", "https://us-east-1-aws-parallelcluster.s3.us-east-1.amazonaws.com"),
        ("cn-north-1", "https://cn-north-1-aws-parallelcluster.s3.cn-north-1.amazonaws.com.cn"),
    ],
)
def test_get_bucket_url(region, expected_url):
    assert_that(get_bucket_url(region)).is_equal_to(expected_url)
