"""This module provides unit tests for the functions in the pcluster.utils module."""

import logging
import os
from itertools import product
from re import escape

import pytest
from assertpy import assert_that
from botocore.exceptions import ClientError, EndpointConnectionError

import pcluster.utils as utils
from pcluster.models.cluster import Cluster, ClusterStack
from pcluster.utils import Cache
from tests.utils import MockedBoto3Request

FAKE_CLUSTER_NAME = "cluster-name"
FAKE_STACK_NAME = f"parallelcluster-{FAKE_CLUSTER_NAME}"


@pytest.fixture()
def boto3_stubber_path():
    """Specify that boto3_mocker should stub calls to boto3 for the pcluster.utils module."""
    return "pcluster.utils.boto3"


def test_get_stack_name():
    """Test utils.get_stack_name."""
    cluster = dummy_cluster(FAKE_CLUSTER_NAME)
    assert_that(cluster.stack_name).is_equal_to(FAKE_STACK_NAME)


def dummy_cluster_stack():
    """Return dummy cluster stack object."""
    return ClusterStack({"StackName": FAKE_STACK_NAME})


def dummy_cluster(name=FAKE_CLUSTER_NAME):
    """Return dummy cluster object."""
    return Cluster(name, stack=dummy_cluster_stack())


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


def test_verify_stack_status_retry(boto3_stubber, mocker):
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
    client = boto3_stubber("cloudformation", mocked_requests)
    verified = utils.verify_stack_status(FAKE_STACK_NAME, ["CREATE_IN_PROGRESS"], "CREATE_COMPLETE", client)
    assert_that(verified).is_false()
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
def test_generate_random_name_with_prefix(bucket_prefix):
    bucket_name = utils.generate_random_name_with_prefix(bucket_prefix)
    max_bucket_name_length = 63
    random_suffix_length = 17  # 16 digits + 1 separator

    pruned_prefix = bucket_prefix[: max_bucket_name_length - len(bucket_prefix) - random_suffix_length]
    assert_that(bucket_name).starts_with(pruned_prefix)
    assert_that(len(bucket_name)).is_equal_to(len(pruned_prefix) + random_suffix_length)

    # Verify bucket name limits: bucket name must be at least 3 and no more than 63 characters long
    assert_that(len(bucket_name)).is_between(3, max_bucket_name_length)


def test_generate_random_prefix():
    prefix = utils.generate_random_prefix()
    assert_that(len(prefix)).is_equal_to(16)


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
    os.environ["AWS_DEFAULT_REGION"] = region
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
            utils.create_s3_bucket(bucket_name)
        if configure_error_message:
            assert_that(delete_s3_bucket_mock.call_count).is_equal_to(1)
    else:
        utils.create_s3_bucket(bucket_name)
        delete_s3_bucket_mock.assert_not_called()


@pytest.mark.parametrize(
    "architecture, supported_oses",
    [
        ("x86_64", ["alinux2", "centos7", "centos8", "ubuntu1804"]),
        ("arm64", ["alinux2", "ubuntu1804", "centos8"]),
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
        ("slurm", ["alinux2", "centos7", "centos8", "ubuntu1804"]),
        ("awsbatch", ["alinux2"]),
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
        "pcluster.utils.InstanceTypeInfo.init_from_instance_type",
        return_value=utils.InstanceTypeInfo({"ProcessorInfo": {"SupportedArchitectures": supported_architectures}}),
    )
    observed_architectures = utils.get_supported_architectures_for_instance_type(instance_type)
    expected_architectures = list(set(supported_architectures) & set(["x86_64", "arm64"]))
    assert_that(observed_architectures).is_equal_to(expected_architectures)
    # optimal case is handled separately; DescribeInstanceTypes shouldn't be called
    if instance_type == "optimal":
        get_instance_types_info_patch.assert_not_called()
    else:
        get_instance_types_info_patch.assert_called_with(instance_type)


@pytest.mark.parametrize(
    "ami_name, error_expected, expected_message",
    [
        # Compatible ami name
        ("ami-xxxaws-parallelcluster-2.9.0xxx", False, ""),
        ("ami-aws-parallelcluster-2.9.0", False, ""),
        ("ami-name-one", False, ""),
        ("aws-parallelcluster-2.9.0-ubuntu-1804-lts-hvm-x86_64-202009142226", False, ""),
        # Incompatible ami name
        (
            "ami-aws-parallelcluster-0.0.0",
            True,
            "This AMI was created with version 0.0.0 of ParallelCluster, but is trying to be used with version 2.9.0."
            " Please either use an AMI created with version 2.9.0 or change your ParallelCluster to version 0.0.0",
        ),
    ],
)
def test_validate_pcluster_version_based_on_ami_name(mocker, ami_name, error_expected, expected_message):
    mocker.patch("pcluster.utils.get_installed_version", return_value="2.9.0")
    if error_expected:
        with pytest.raises(SystemExit, match=expected_message):
            utils.validate_pcluster_version_based_on_ami_name(ami_name)
    else:
        utils.validate_pcluster_version_based_on_ami_name(ami_name)


@pytest.mark.parametrize(
    "raise_error_api_function, raise_error_parsing_function, types_parsed_from_emsg_are_known",
    product([True, False], repeat=3),
)
def test_get_supported_batch_instance_types(
    mocker, raise_error_api_function, raise_error_parsing_function, types_parsed_from_emsg_are_known
):
    """Verify functions are called and errors are handled as expected when getting supported batch instance types."""
    # Dummy values
    dummy_error_message = "dummy error message"
    dummy_batch_instance_types = ["batch-instance-type"]
    dummy_batch_instance_families = ["batch-instance-family"]
    dummy_all_instance_types = dummy_batch_instance_types + ["non-batch-instance-type"]
    dummy_all_instance_families = dummy_batch_instance_families + ["non-batch-instance-family"]
    # Mock all functions called by the function
    api_function_patch = mocker.patch(
        "pcluster.utils._get_cce_emsg_containing_supported_instance_types",
        side_effect=utils.BatchErrorMessageParsingException
        if raise_error_api_function
        else lambda: dummy_error_message,
    )
    parsing_function_patch = mocker.patch(
        "pcluster.utils._parse_supported_instance_types_and_families_from_cce_emsg",
        side_effect=utils.BatchErrorMessageParsingException
        if raise_error_parsing_function
        else lambda emsg: dummy_batch_instance_types + dummy_batch_instance_families,
    )
    supported_instance_types_patch = mocker.patch(
        "pcluster.utils.get_supported_instance_types", return_value=dummy_all_instance_types
    )
    get_instance_families_patch = mocker.patch(
        "pcluster.utils._get_instance_families_from_types", return_value=dummy_all_instance_families
    )
    candidates_are_supported_patch = mocker.patch(
        "pcluster.utils._batch_instance_types_and_families_are_supported", return_value=types_parsed_from_emsg_are_known
    )
    # this list contains values that are assumed to be supported instance types in all regions
    assumed_supported = ["optimal"]
    returned_value = utils.get_supported_batch_instance_types()
    # The functions that call the Batch CreateComputeEnvironment API, and those that get all
    # supported instance types and families should always be called.
    assert_that(api_function_patch.call_count).is_equal_to(1)
    assert_that(supported_instance_types_patch.call_count).is_equal_to(1)
    get_instance_families_patch.assert_called_with(dummy_all_instance_types)
    # The function that parses the error message returned by the Batch API is only called if the
    # function that calls the API succeeds.
    if raise_error_api_function:
        parsing_function_patch.assert_not_called()
    else:
        parsing_function_patch.assert_called_with(dummy_error_message)
    # The function that ensures the values parsed from the CCE error message are valid is only called if
    # the API call and parsing succeed.
    if any([raise_error_api_function, raise_error_parsing_function]):
        candidates_are_supported_patch.assert_not_called()
    else:
        candidates_are_supported_patch.assert_called_with(
            dummy_batch_instance_types + dummy_batch_instance_families,
            dummy_all_instance_types + dummy_all_instance_families + assumed_supported,
        )
    # If either of the functions don't succeed, get_supported_instance_types return value should be
    # used as a fallback.
    assert_that(returned_value).is_equal_to(
        dummy_all_instance_types + dummy_all_instance_families + assumed_supported
        if any([raise_error_api_function, raise_error_parsing_function, not types_parsed_from_emsg_are_known])
        else dummy_batch_instance_types + dummy_batch_instance_families
    )


@pytest.mark.parametrize(
    "api_emsg, match_expected, expected_return_value",
    [
        # Positives
        # Expected format using various instance types
        ("be one of [u-6tb1.metal, i3en.metal-2tb]", True, ["u-6tb1.metal", "i3en.metal-2tb"]),
        ("be one of [i3en.metal-2tb, u-6tb1.metal]", True, ["i3en.metal-2tb", "u-6tb1.metal"]),
        ("be one of [c5n.xlarge, m6g.xlarge]", True, ["c5n.xlarge", "m6g.xlarge"]),
        # Whitespace within the brackets shouldn't matter
        ("be one of [c5.xlarge,m6g.xlarge]", True, ["c5.xlarge", "m6g.xlarge"]),
        ("be one of [   c5.xlarge,     m6g.xlarge]", True, ["c5.xlarge", "m6g.xlarge"]),
        ("be one of [c5.xlarge    ,m6g.xlarge    ]", True, ["c5.xlarge", "m6g.xlarge"]),
        # Instance families as well as types must be handled.
        ("be one of [  c5    ,    m6g  ]", True, ["c5", "m6g"]),
        # The amount of whitespace between the words preceding the brackets doesn't matter.
        ("be one of      [c5.xlarge, m6g.xlarge]", True, ["c5.xlarge", "m6g.xlarge"]),
        ("be one of[c5.xlarge, m6g.xlarge]", True, ["c5.xlarge", "m6g.xlarge"]),
        ("     be            one     of[c5.xlarge, m6g.xlarge]", True, ["c5.xlarge", "m6g.xlarge"]),
        # Negatives
        # Brackets are what's used to determine where the instance type list starts.
        # If there are no brackets, there will be no match.
        ("be one of (c5.xlarge, m6g.xlarge)", False, None),
        ("be one of [c5.xlarge, m6g.xlarge", False, None),
        ("be one of c5.xlarge, m6g.xlarge]", False, None),
        # A comma must be used within the brackets.
        ("be one of [c5.xlarge| m6g.xlarge]", False, None),
    ],
)
def test_parse_supported_instance_types_and_families_from_cce_emsg(
    caplog, api_emsg, match_expected, expected_return_value
):
    """Verify parsing supported instance types from the CreateComputeEnvironment error message works as expected."""
    results_log_msg_preamble = "Parsed the following instance types and families from Batch CCE error message:"
    caplog.set_level(logging.DEBUG)
    if match_expected:
        assert_that(utils._parse_supported_instance_types_and_families_from_cce_emsg(api_emsg)).is_equal_to(
            expected_return_value
        )
        assert_that(caplog.text).contains(results_log_msg_preamble)
    else:
        with pytest.raises(
            utils.BatchErrorMessageParsingException,
            match="Could not parse supported instance types from the following: {0}".format(escape(api_emsg)),
        ):
            utils._parse_supported_instance_types_and_families_from_cce_emsg(api_emsg)
        assert_that(caplog.text).does_not_contain(results_log_msg_preamble)


@pytest.mark.parametrize("error_type", [ClientError, EndpointConnectionError(endpoint_url="dummy_endpoint"), None])
def test_get_cce_emsg_containing_supported_instance_types(mocker, boto3_stubber, error_type):
    """Verify CreateComputeEnvironment call to get error message with supported instance types behaves as expected."""
    dummy_error_message = "dummy message"
    call_api_patch = None
    if error_type == ClientError:
        mocked_requests = [
            MockedBoto3Request(
                method="create_compute_environment",
                expected_params={
                    "computeEnvironmentName": "dummy",
                    "type": "MANAGED",
                    "computeResources": {
                        "type": "EC2",
                        "minvCpus": 0,
                        "maxvCpus": 0,
                        "instanceTypes": ["p8.84xlarge"],
                        "subnets": ["subnet-12345"],
                        "securityGroupIds": ["sg-12345"],
                        "instanceRole": "ecsInstanceRole",
                    },
                    "serviceRole": "AWSBatchServiceRole",
                },
                response=dummy_error_message,
                generate_error=True,
            )
        ]
        boto3_stubber("batch", mocked_requests)
    else:
        call_api_patch = mocker.patch(
            "pcluster.utils._call_create_compute_environment_with_bad_instance_type",
            side_effect=error_type,
        )

    if error_type == ClientError:
        return_value = utils._get_cce_emsg_containing_supported_instance_types()
        assert_that(return_value).is_equal_to(dummy_error_message)
    else:
        expected_message = (
            "Could not connect to the batch endpoint"
            if isinstance(error_type, EndpointConnectionError)
            else "did not result in an error as expected"
        )
        with pytest.raises(utils.BatchErrorMessageParsingException, match=expected_message):
            utils._get_cce_emsg_containing_supported_instance_types()
        assert_that(call_api_patch.call_count).is_equal_to(1)


@pytest.mark.parametrize("generate_error", [True, False])
def test_get_supported_instance_types(mocker, boto3_stubber, generate_error):
    """Verify that get_supported_instance_types behaves as expected."""
    dummy_message = "dummy error message"
    dummy_instance_types = ["c5.xlarge", "m6g.xlarge"]
    error_patch = mocker.patch("pcluster.utils.error")
    mocked_requests = [
        MockedBoto3Request(
            method="describe_instance_type_offerings",
            expected_params={},
            response=dummy_message
            if generate_error
            else {"InstanceTypeOfferings": [{"InstanceType": instance_type} for instance_type in dummy_instance_types]},
            generate_error=generate_error,
        )
    ]
    boto3_stubber("ec2", mocked_requests)
    return_value = utils.get_supported_instance_types()
    if generate_error:
        expected_error_message = (
            "Error when getting supported instance types via DescribeInstanceTypeOfferings: {0}".format(dummy_message)
        )
        error_patch.assert_called_with(expected_error_message)
    else:
        assert_that(return_value).is_equal_to(dummy_instance_types)
        error_patch.assert_not_called()


@pytest.mark.parametrize(
    "candidates, knowns",
    [
        (["c5.xlarge", "m6g"], ["c5.xlarge", "c5", "m6g.xlarge", "m6g"]),
        (["bad-candidate"], ["c5.xlarge", "c5", "m6g.xlarge", "m6g"]),
        (["optimal"], []),
    ],
)
def test_batch_instance_types_and_families_are_supported(caplog, candidates, knowns):
    """Verify function that describes whether all given instance types/families are supported behaves as expected."""
    caplog.set_level(logging.DEBUG)
    unknown_candidates = [candidate for candidate in candidates if candidate not in knowns]
    expected_return_value = not unknown_candidates
    observed_return_value = utils._batch_instance_types_and_families_are_supported(candidates, knowns)
    assert_that(observed_return_value).is_equal_to(expected_return_value)
    if unknown_candidates:
        log_msg = "Found the following unknown instance types/families: {0}".format(" ".join(unknown_candidates))
        assert_that(caplog.text).contains(log_msg)


@pytest.mark.parametrize(
    "instance_types, error_expected, expected_return_value",
    [
        (["m6g.xlarge"], False, ["m6g"]),
        (["m6g.xlarge", "m6g-."], False, ["m6g", "m6g-"]),
        (["m6g.xlarge", ".2xlarge"], True, ["m6g"]),
    ],
)
def test_get_instance_families_from_types(caplog, instance_types, error_expected, expected_return_value):
    """Verify the function that parses instance families from instance types works as expected."""
    error_message_prefix = "Unable to parse instance family for instance type"
    caplog.set_level(logging.DEBUG)
    assert_that(utils._get_instance_families_from_types(instance_types)).contains_only(*expected_return_value)
    if error_expected:
        assert_that(caplog.text).contains(error_message_prefix)
    else:
        assert_that(caplog.text).does_not_contain(error_message_prefix)


@pytest.mark.parametrize(
    "candidate, expected_return_value",
    [
        ("m6g.xlarge", True),
        ("c5n.xlarge", True),
        ("i3en.metal-2tb", True),
        ("u-6tb1.metal", True),
        ("m6g", False),
        ("c5n", False),
        ("u-6tb1", False),
        ("i3en", False),
        ("optimal", False),
    ],
)
def test_is_instance_type_format(candidate, expected_return_value):
    """Verify function that decides whether or not a string represents an instance type behaves as expected."""
    assert_that(utils.is_instance_type_format(candidate)).is_equal_to(expected_return_value)


@pytest.mark.parametrize(
    "snapshot_id, raise_exceptions, error_message",
    [
        ("snap-1234567890abcdef0", False, None),
        ("snap-1234567890abcdef0", True, None),
        ("snap-1234567890abcdef0", False, "Some error message"),
        ("snap-1234567890abcdef0", True, "Some error message"),
    ],
)
def test_get_ebs_snapshot_info(boto3_stubber, snapshot_id, raise_exceptions, error_message):
    """Verify that get_snapshot_info makes the expected API call."""
    response = {
        "Description": "This is my snapshot",
        "Encrypted": False,
        "VolumeId": "vol-049df61146c4d7901",
        "State": "completed",
        "VolumeSize": 120,
        "StartTime": "2014-02-28T21:28:32.000Z",
        "Progress": "100%",
        "OwnerId": "012345678910",
        "SnapshotId": "snap-1234567890abcdef0",
    }
    describe_snapshots_response = {"Snapshots": [response]}

    mocked_requests = [
        MockedBoto3Request(
            method="describe_snapshots",
            response=describe_snapshots_response if error_message is None else error_message,
            expected_params={"SnapshotIds": ["snap-1234567890abcdef0"]},
            generate_error=error_message is not None,
        )
    ]
    boto3_stubber("ec2", mocked_requests)
    if error_message is None:
        assert_that(utils.get_ebs_snapshot_info(snapshot_id, raise_exceptions=raise_exceptions)).is_equal_to(response)
    elif error_message and raise_exceptions:
        with pytest.raises(ClientError, match=error_message) as clienterror:
            utils.get_ebs_snapshot_info(snapshot_id, raise_exceptions=raise_exceptions)
            assert_that(clienterror.value.code).is_not_equal_to(0)
    else:
        with pytest.raises(SystemExit, match=error_message) as sysexit:
            utils.get_ebs_snapshot_info(snapshot_id, raise_exceptions=raise_exceptions)
            assert_that(sysexit.value.code).is_not_equal_to(0)


@pytest.mark.cache
class TestCache:
    invocations = []

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        utils.Cache.clear_all()

    @pytest.fixture(autouse=True)
    def clear_invocations(self):
        del self.invocations[:]

    @pytest.fixture
    def disabled_cache(self):
        os.environ["PCLUSTER_CACHE_DISABLED"] = "true"
        yield
        del os.environ["PCLUSTER_CACHE_DISABLED"]

    @staticmethod
    @Cache.cached
    def _cached_method_1(arg1, arg2):
        TestCache.invocations.append((arg1, arg2))
        return arg1, arg2

    @staticmethod
    @Cache.cached
    def _cached_method_2(arg1, arg2):
        TestCache.invocations.append((arg1, arg2))
        return arg1, arg2

    def test_cached_method(self):
        for _ in range(0, 2):
            assert_that(self._cached_method_1(1, 2)).is_equal_to((1, 2))
            assert_that(self._cached_method_2(1, 2)).is_equal_to((1, 2))
            assert_that(self._cached_method_1(2, 1)).is_equal_to((2, 1))
            assert_that(self._cached_method_1(1, arg2=2)).is_equal_to((1, 2))
            assert_that(self._cached_method_1(arg1=1, arg2=2)).is_equal_to((1, 2))

        assert_that(self.invocations).is_length(5)

    def test_disabled_cache(self, disabled_cache):
        assert_that(self._cached_method_1(1, 2)).is_equal_to((1, 2))
        assert_that(self._cached_method_1(1, 2)).is_equal_to((1, 2))

        assert_that(self.invocations).is_length(2)

    def test_clear_all(self):
        for _ in range(0, 2):
            assert_that(self._cached_method_1(1, 2)).is_equal_to((1, 2))
            assert_that(self._cached_method_2(1, 2)).is_equal_to((1, 2))

        Cache.clear_all()

        for _ in range(0, 2):
            assert_that(self._cached_method_1(1, 2)).is_equal_to((1, 2))
            assert_that(self._cached_method_2(1, 2)).is_equal_to((1, 2))

        assert_that(self.invocations).is_length(4)


class TestInstanceTypeInfo:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        utils.Cache.clear_all()

    def test_init_from_instance_type(self, boto3_stubber, capsys):
        mocked_requests = [
            MockedBoto3Request(
                method="describe_instance_types",
                response={
                    "InstanceTypes": [
                        {
                            "InstanceType": "c4.xlarge",
                            "VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2, "DefaultThreadsPerCore": 2},
                            "NetworkInfo": {"EfaSupported": False, "MaximumNetworkCards": 1},
                            "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
                        }
                    ]
                },
                expected_params={"InstanceTypes": ["c4.xlarge"]},
            ),
            MockedBoto3Request(
                method="describe_instance_types",
                response={
                    "InstanceTypes": [
                        {
                            "InstanceType": "g4dn.metal",
                            "VCpuInfo": {"DefaultVCpus": 96},
                            "GpuInfo": {"Gpus": [{"Name": "T4", "Manufacturer": "NVIDIA", "Count": 8}]},
                            "NetworkInfo": {"EfaSupported": True, "MaximumNetworkCards": 4},
                            "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
                        }
                    ]
                },
                expected_params={"InstanceTypes": ["g4dn.metal"]},
            ),
            MockedBoto3Request(
                method="describe_instance_types",
                response={
                    "InstanceTypes": [
                        {
                            "InstanceType": "g4ad.16xlarge",
                            "VCpuInfo": {"DefaultVCpus": 64},
                            "GpuInfo": {"Gpus": [{"Name": "*", "Manufacturer": "AMD", "Count": 4}]},
                            "NetworkInfo": {"EfaSupported": False, "MaximumNetworkCards": 1},
                            "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
                        }
                    ]
                },
                expected_params={"InstanceTypes": ["g4ad.16xlarge"]},
            ),
        ]
        boto3_stubber("ec2", mocked_requests)

        for _ in range(0, 2):
            c4_instance_info = utils.InstanceTypeInfo.init_from_instance_type("c4.xlarge")
            g4dn_instance_info = utils.InstanceTypeInfo.init_from_instance_type("g4dn.metal")
            g4ad_instance_info = utils.InstanceTypeInfo.init_from_instance_type("g4ad.16xlarge")

        assert_that(c4_instance_info.gpu_count()).is_equal_to(0)
        assert_that(capsys.readouterr().out).is_empty()
        assert_that(c4_instance_info.max_network_interface_count()).is_equal_to(1)
        assert_that(c4_instance_info.default_threads_per_core()).is_equal_to(2)
        assert_that(c4_instance_info.vcpus_count()).is_equal_to(4)
        assert_that(c4_instance_info.supported_architecture()).is_equal_to(["x86_64"])
        assert_that(c4_instance_info.is_efa_supported()).is_equal_to(False)

        assert_that(g4dn_instance_info.gpu_count()).is_equal_to(8)
        assert_that(capsys.readouterr().out).is_empty()
        assert_that(g4dn_instance_info.max_network_interface_count()).is_equal_to(4)
        assert_that(g4dn_instance_info.default_threads_per_core()).is_equal_to(2)
        assert_that(g4dn_instance_info.vcpus_count()).is_equal_to(96)
        assert_that(g4dn_instance_info.supported_architecture()).is_equal_to(["x86_64"])
        assert_that(g4dn_instance_info.is_efa_supported()).is_equal_to(True)

        assert_that(g4ad_instance_info.gpu_count()).is_equal_to(0)
        assert_that(capsys.readouterr().out).matches("not offer native support for 'AMD' GPUs.")
        assert_that(g4ad_instance_info.max_network_interface_count()).is_equal_to(1)
        assert_that(g4ad_instance_info.default_threads_per_core()).is_equal_to(2)
        assert_that(g4ad_instance_info.vcpus_count()).is_equal_to(64)
        assert_that(g4ad_instance_info.supported_architecture()).is_equal_to(["x86_64"])
        assert_that(g4ad_instance_info.is_efa_supported()).is_equal_to(False)

    def test_init_from_instance_type_failure(self, boto3_stubber):
        boto3_stubber(
            "ec2",
            2
            * [
                MockedBoto3Request(
                    method="describe_instance_types",
                    expected_params={"InstanceTypes": ["g4dn.metal"]},
                    generate_error=True,
                    response="Error message",
                )
            ],
        )
        error_message = "Failed when retrieving instance type data for instance g4dn.metal: Error message"
        with pytest.raises(SystemExit, match=error_message):
            utils.InstanceTypeInfo.init_from_instance_type("g4dn.metal")

        utils.InstanceTypeInfo.init_from_instance_type("g4dn.metal", exit_on_error=False)
