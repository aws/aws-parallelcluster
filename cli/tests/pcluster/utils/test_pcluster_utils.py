"""This module provides unit tests for the functions in the pcluster.utils module."""

import json

import pytest
from assertpy import assert_that
from botocore.exceptions import ClientError

import pcluster.utils as utils
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
    "region,create_error_message,configure_error_message",
    [
        ("eu-west-1", None, None),
        ("us-east-1", None, None),
        ("eu-west-1", "An error occurred", None),
        ("eu-west-1", None, "An error occurred"),
    ],
)
def test_create_s3_bucket(region, create_error_message, configure_error_message, boto3_stubber, mocker):
    bucket_name = "test"
    expected_params = {"Bucket": bucket_name}
    if region != "us-east-1":
        # LocationConstraint specifies the region where the bucket will be created.
        # When the region is us-east-1 we are not specifying this parameter because it's the default region.
        expected_params["CreateBucketConfiguration"] = {"LocationConstraint": region}

    delete_s3_bucket_mock = mocker.patch("pcluster.utils.delete_s3_bucket", auto_spec=True)

    mocked_requests = [
        MockedBoto3Request(
            method="create_bucket",
            expected_params=expected_params,
            response={"Location": bucket_name},
            generate_error=create_error_message is not None,
        )
    ]
    if not create_error_message:
        mocked_requests += [
            MockedBoto3Request(
                method="put_bucket_versioning",
                expected_params={"Bucket": bucket_name, "VersioningConfiguration": {"Status": "Enabled"}},
                response={},
                generate_error=configure_error_message is not None,
            )
        ]
        if not configure_error_message:
            mocked_requests += [
                MockedBoto3Request(
                    method="put_bucket_encryption",
                    expected_params={
                        "Bucket": bucket_name,
                        "ServerSideEncryptionConfiguration": {
                            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
                        },
                    },
                    response={},
                ),
                MockedBoto3Request(
                    method="put_bucket_policy",
                    expected_params={
                        "Bucket": bucket_name,
                        "Policy": (
                            '{{"Id":"DenyHTTP","Version":"2012-10-17","Statement":[{{"Sid":"AllowSSLRequestsOnly",'
                            '"Action":"s3:*","Effect":"Deny","Resource":["arn:aws:s3:::{bucket_name}","arn:aws:s3:::'
                            '{bucket_name}/*"],"Condition":{{"Bool":{{"aws:SecureTransport":"false"}}}},'
                            '"Principal":"*"}}]}}'
                        ).format(bucket_name=bucket_name),
                    },
                    response={},
                ),
            ]

    boto3_stubber("s3", mocked_requests)
    if create_error_message or configure_error_message:
        with pytest.raises(ClientError, match=create_error_message or configure_error_message):
            utils.create_s3_bucket(bucket_name, region)
        if configure_error_message:
            assert_that(delete_s3_bucket_mock.call_count).is_equal_to(1)
    else:
        utils.create_s3_bucket(bucket_name, region)
        delete_s3_bucket_mock.assert_not_called()


@pytest.mark.parametrize(
    "architecture, supported_oses",
    [
        ("x86_64", ["alinux", "alinux2", "centos6", "centos7", "ubuntu1604", "ubuntu1804"]),
        ("arm64", ["alinux2", "ubuntu1804"]),
        # doesn't check architecture's validity, only whether it's x86_64 or not
        ("madeup-architecture", ["alinux2", "ubuntu1804"]),
    ],
)
def test_get_supported_os_for_architecture(architecture, supported_oses):
    """Verify that the expected OSes are supported based on a given architecture."""
    assert_that(utils.get_supported_os_for_architecture(architecture)).contains_only(
        *supported_oses
    ).does_not_contain_duplicates()


@pytest.mark.parametrize(
    "scheduler, supported_oses",
    [
        ("sge", ["alinux", "alinux2", "centos6", "centos7", "ubuntu1604", "ubuntu1804"]),
        ("slurm", ["alinux", "alinux2", "centos6", "centos7", "ubuntu1604", "ubuntu1804"]),
        ("torque", ["alinux", "alinux2", "centos6", "centos7", "ubuntu1604", "ubuntu1804"]),
        ("awsbatch", ["alinux2", "alinux"]),
        # doesn't check architecture's validity, only whether it's awsbatch or not
        ("madeup-scheduler", ["alinux", "alinux2", "centos6", "centos7", "ubuntu1604", "ubuntu1804"]),
    ],
)
def test_get_supported_os_for_scheduler(scheduler, supported_oses):
    """Verify that the expected OSes are supported based on a given architecture."""
    assert_that(utils.get_supported_os_for_scheduler(scheduler)).contains_only(
        *supported_oses
    ).does_not_contain_duplicates()


@pytest.mark.parametrize(
    "image_ids, response, error_message",
    [(["ami-1"], [{"ImageId": "ami-1"}], None), (["ami-1"], [{"ImageId": "ami-1"}], "Some error message")],
)
def test_get_info_for_amis(boto3_stubber, image_ids, response, error_message):
    """Verify get_info_for_amis returns the expected portion of the response, and that errors cause nonzero exit."""
    mocked_requests = [
        MockedBoto3Request(
            method="describe_images",
            response=error_message or {"Images": response},
            expected_params={"ImageIds": image_ids},
            generate_error=error_message is not None,
        )
    ]
    boto3_stubber("ec2", mocked_requests)
    if error_message is None:
        assert_that(utils.get_info_for_amis(image_ids)).is_equal_to(response)
    else:
        with pytest.raises(SystemExit, match=error_message) as sysexit:
            utils.get_info_for_amis(image_ids)
        assert_that(sysexit.value.code).is_not_equal_to(0)


@pytest.mark.parametrize(
    "instance_types, error_message, fail_on_error",
    [
        # Test when calling for single instance types
        (["t2.micro"], None, None),
        (["bad.instance.type"], "some error message", True),
        (["bad.instance.type"], "some error message", False),
        # Test when calling for multiple instance types
        (["t2.micro", "t2.xlarge"], None, None),
        (["a1.medium", "m6g.xlarge"], None, None),
        (["bad.instance.type1", "bad.instance.type2"], "some error message", True),
        (["bad.instance.type1", "bad.instance.type2"], "some error message", False),
    ],
)
def test_get_instance_types_info(boto3_stubber, capsys, instance_types, error_message, fail_on_error):
    """Verify that get_instance_types_info makes the expected API call."""
    response_dict = {"InstanceTypes": [{"InstanceType": instance_type} for instance_type in instance_types]}
    mocked_requests = [
        MockedBoto3Request(
            method="describe_instance_types",
            response=response_dict if error_message is None else error_message,
            expected_params={"InstanceTypes": instance_types},
            generate_error=error_message,
        )
    ]
    boto3_stubber("ec2", mocked_requests)
    if error_message and fail_on_error:
        full_error_message = "calling DescribeInstanceTypes for instances {0}: {1}".format(
            ", ".join(instance_types), error_message
        )
        with pytest.raises(SystemExit, match=full_error_message) as sysexit:
            utils.get_instance_types_info(instance_types, fail_on_error)
        assert_that(sysexit.value.code).is_not_equal_to(0)
    elif error_message:
        utils.get_instance_types_info(instance_types, fail_on_error)
        assert_that(capsys.readouterr().out).matches(error_message)
    else:
        instance_types_info = utils.get_instance_types_info(instance_types, fail_on_error)
        assert_that(instance_types_info).is_equal_to(response_dict.get("InstanceTypes"))


@pytest.mark.parametrize(
    "instance_type, supported_architectures, error_message",
    [
        ("optimal", ["x86_64"], None),
        ("t2.micro", ["x86_64", "i386"], None),
        ("a1.medium", ["arm64"], None),
        ("valid.exotic.arch.instance", ["exoticArch"], None),
    ],
)
def test_get_supported_architectures_for_instance_type(mocker, instance_type, supported_architectures, error_message):
    """Verify that get_supported_architectures_for_instance_type behaves as expected for various cases."""
    get_instance_types_info_patch = mocker.patch(
        "pcluster.utils.get_instance_types_info",
        return_value=[{"ProcessorInfo": {"SupportedArchitectures": supported_architectures}}],
    )
    observed_architectures = utils.get_supported_architectures_for_instance_type(instance_type)
    expected_architectures = list(set(supported_architectures) & set(["x86_64", "arm64"]))
    assert_that(observed_architectures).is_equal_to(expected_architectures)
    # optimal case is handled separately; DescribeInstanceTypes shouldn't be called
    if instance_type == "optimal":
        get_instance_types_info_patch.assert_not_called()
    else:
        get_instance_types_info_patch.assert_called_with([instance_type])


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
    "scheduler, expected_is_hit_enabled",
    [
        ("sge", False),
        ("slurm", True),
        ("torque", False),
        ("awsbatch", False),
        # doesn't check scheduler's validity, only whether it's slurm or not
        ("madeup-scheduler", False),
    ],
)
def test_is_hit_enabled_cluster(scheduler, expected_is_hit_enabled):
    """Verify that the expected schedulers are hit enabled."""
    assert_that(utils.is_hit_enabled_scheduler(scheduler)).is_equal_to(expected_is_hit_enabled)


@pytest.mark.parametrize(
    "region, expected_url",
    [
        ("us-east-1", "https://us-east-1-aws-parallelcluster.s3.us-east-1.amazonaws.com"),
        ("cn-north-1", "https://cn-north-1-aws-parallelcluster.s3.cn-north-1.amazonaws.com.cn"),
    ],
)
def test_get_bucket_url(region, expected_url):
    assert_that(get_bucket_url(region)).is_equal_to(expected_url)
