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
import logging
import os
from itertools import product
from re import escape

import pytest
from assertpy import assert_that
from botocore.exceptions import EndpointConnectionError

import pcluster.validators.awsbatch_validators as awsbatch_validators
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.aws_resources import InstanceTypeInfo
from pcluster.aws.batch import BatchErrorMessageParsingException
from pcluster.validators.awsbatch_validators import (
    AwsBatchComputeInstanceTypeValidator,
    AwsBatchComputeResourceSizeValidator,
    AwsBatchFsxValidator,
    AwsBatchInstancesArchitectureCompatibilityValidator,
)
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.utils import MockedBoto3Request

from .utils import assert_failure_messages


@pytest.fixture()
def boto3_stubber_path():
    """Specify that boto3_mocker should stub calls to boto3 for the pcluster.utils module."""
    return "pcluster.aws.common.boto3"


@pytest.mark.parametrize(
    "instance_type, max_vcpus, expected_message",
    [
        ("t2.micro", 2, "Max vCPUs must be greater than or equal to 4"),
        ("t2.micro", 4, None),
        ("p4d.24xlarge", 4, None),
        ("c4.xlarge", 4, "is not supported"),
        ("t2", 2, None),  # t2 family
        ("optimal", 4, None),
    ],
)
def test_compute_instance_type_validator(mocker, instance_type, max_vcpus, expected_message):
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.list_instance_types", return_value=["t2.micro", "p4d.24xlarge"])
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.get_instance_type_info",
        return_value=InstanceTypeInfo(
            {
                "InstanceType": instance_type,
                "VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2},
                "NetworkInfo": {"EfaSupported": False},
            }
        ),
    )
    actual_failures = AwsBatchComputeInstanceTypeValidator().execute([instance_type], max_vcpus)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "min_vcpus, desired_vcpus, max_vcpus, expected_message",
    [
        (1, 2, 3, None),
        (3, 2, 3, "desired vCPUs must be greater than or equal to min vCPUs"),
        (1, 4, 3, "desired vCPUs must be fewer than or equal to max vCPUs"),
        (4, 4, 3, "Max vCPUs must be greater than or equal to min vCPUs"),
    ],
)
def test_awsbatch_compute_resource_size_validator(min_vcpus, desired_vcpus, max_vcpus, expected_message):
    actual_failures = AwsBatchComputeResourceSizeValidator().execute(min_vcpus, desired_vcpus, max_vcpus)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "head_node_architecture, compute_architecture, compute_instance_types, expected_message",
    [
        ("x86_64", "x86_64", ["optimal"], None),
        # Function to get supported architectures shouldn't be called because compute instance types arg
        # are instance families.
        ("x86_64", None, ["m6g"], "Not validating architecture"),
        ("x86_64", None, ["c5"], "Not validating architecture"),
        # The validator must handle the case where compute instance type is a CSV list
        ("arm64", "arm64", ["m6g.xlarge", "r6g.xlarge"], None),
        (
            "x86_64",
            "arm64",
            ["m6g.xlarge", "r6g.xlarge"],
            "none of which is compatible with the architecture.*supported by the head node instance type",
        ),
    ],
)
def test_awsbatch_instances_architecture_compatibility_validator(
    mocker, head_node_architecture, compute_architecture, compute_instance_types, expected_message
):
    def _internal_is_instance_type(itype):
        return "." in itype

    mock_aws_api(mocker)
    supported_architectures_patch = mocker.patch(
        "pcluster.aws.ec2.Ec2Client.get_supported_architectures", return_value=[compute_architecture]
    )
    is_instance_type_patch = mocker.patch(
        "pcluster.validators.awsbatch_validators.AwsBatchInstancesArchitectureCompatibilityValidator."
        "_is_instance_type_format",
        side_effect=_internal_is_instance_type,
    )

    actual_failures = AwsBatchInstancesArchitectureCompatibilityValidator().execute(
        compute_instance_types, head_node_architecture
    )
    assert_failure_messages(actual_failures, expected_message)
    if expected_message:
        assert_that(len(actual_failures)).is_equal_to(len(compute_instance_types))

    non_instance_families = [
        instance_type for instance_type in compute_instance_types if _internal_is_instance_type(instance_type)
    ]
    assert_that(supported_architectures_patch.call_count).is_equal_to(len(non_instance_families))
    assert_that(is_instance_type_patch.call_count).is_equal_to(len(compute_instance_types))


@pytest.mark.parametrize(
    "raise_error_parsing_function, types_parsed_from_emsg_are_known", product([True, False], repeat=2)
)
def test_get_supported_batch_instance_types(mocker, raise_error_parsing_function, types_parsed_from_emsg_are_known):
    """Verify functions are called and errors are handled as expected when getting supported batch instance types."""
    # Dummy values
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    dummy_batch_instance_types = ["batch-instance-type"]
    dummy_batch_instance_families = ["batch-instance-family"]
    dummy_all_instance_types = dummy_batch_instance_types + ["non-batch-instance-type"]
    dummy_all_instance_families = dummy_batch_instance_families + ["non-batch-instance-family"]
    # Mock all functions called by the function
    parsing_function_patch = mocker.patch(
        "pcluster.aws.batch.BatchClient.get_supported_instance_types_and_families",
        side_effect=BatchErrorMessageParsingException
        if raise_error_parsing_function
        else lambda: dummy_batch_instance_types + dummy_batch_instance_families,
    )
    supported_instance_types_patch = mocker.patch(
        "pcluster.aws.ec2.Ec2Client.list_instance_types", return_value=dummy_all_instance_types
    )
    get_instance_families_patch = mocker.patch(
        "pcluster.validators.awsbatch_validators._get_instance_families_from_types",
        return_value=dummy_all_instance_families,
    )
    candidates_are_supported_patch = mocker.patch(
        "pcluster.validators.awsbatch_validators._batch_instance_types_and_families_are_supported",
        return_value=types_parsed_from_emsg_are_known,
    )
    # this list contains values that are assumed to be supported instance types in all regions
    assumed_supported = ["optimal"]
    returned_value = awsbatch_validators._get_supported_batch_instance_types()
    # The functions that call the Batch CreateComputeEnvironment API, and those that get all
    # supported instance types and families should always be called.
    assert_that(supported_instance_types_patch.call_count).is_equal_to(1)
    get_instance_families_patch.assert_called_with(dummy_all_instance_types)
    # The function that parses the error message returned by the Batch API is only called if the
    # function that calls the API succeeds.
    parsing_function_patch.assert_called()
    # The function that ensures the values parsed from the CCE error message are valid is only called if
    # the API call and parsing succeed.
    if raise_error_parsing_function:
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
        if any([raise_error_parsing_function, not types_parsed_from_emsg_are_known])
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
    mocker, caplog, api_emsg, match_expected, expected_return_value
):
    """Verify parsing supported instance types from the CreateComputeEnvironment error message works as expected."""
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    mocker.patch(
        "pcluster.aws.batch.BatchClient._get_cce_emsg_containing_supported_instance_types", return_value=api_emsg
    )
    results_log_msg_preamble = "Parsed the following instance types and families from Batch CCE error message:"
    caplog.set_level(logging.DEBUG, logger="pcluster")
    if match_expected:
        assert_that(AWSApi.instance().batch.get_supported_instance_types_and_families()).is_equal_to(
            expected_return_value
        )
        assert_that(caplog.text).contains(results_log_msg_preamble)
    else:
        with pytest.raises(
            BatchErrorMessageParsingException,
            match="Could not parse supported instance types from the following: {0}".format(escape(api_emsg)),
        ):
            AWSApi.instance().batch.get_supported_instance_types_and_families()
        assert_that(caplog.text).does_not_contain(results_log_msg_preamble)


@pytest.mark.parametrize("error_type", [EndpointConnectionError(endpoint_url="dummy_endpoint"), None])
def test_get_cce_emsg_containing_supported_instance_types(mocker, error_type):
    """Verify CreateComputeEnvironment call to get error message with supported instance types behaves as expected."""
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    call_api_patch = mocker.patch(
        "pcluster.aws.batch.BatchClient._call_create_compute_environment_with_bad_instance_type",
        side_effect=error_type,
    )
    mocker.patch("pcluster.aws.batch.get_region", return_value="eu-west-2")
    expected_message = (
        "Could not connect to the batch endpoint for region eu-west-2"
        if isinstance(error_type, EndpointConnectionError)
        else "did not result in an error as expected"
    )
    with pytest.raises(BatchErrorMessageParsingException, match=expected_message):
        AWSApi.instance().batch._get_cce_emsg_containing_supported_instance_types()
    assert_that(call_api_patch.call_count).is_equal_to(1)


def test_get_cce_emsg_containing_supported_instance_types_client_error(boto3_stubber):
    """Verify CreateComputeEnvironment call to get error message with supported instance types behaves as expected."""
    dummy_error_message = "dummy message"
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
    return_value = AWSApi.instance().batch._get_cce_emsg_containing_supported_instance_types()
    assert_that(return_value).is_equal_to(dummy_error_message)


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
    caplog.set_level(logging.DEBUG, logger="pcluster")
    unknown_candidates = [candidate for candidate in candidates if candidate not in knowns]
    expected_return_value = not unknown_candidates
    observed_return_value = awsbatch_validators._batch_instance_types_and_families_are_supported(candidates, knowns)
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
    caplog.set_level(logging.DEBUG, logger="pcluster")
    assert_that(awsbatch_validators._get_instance_families_from_types(instance_types)).contains_only(
        *expected_return_value
    )
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
    assert_that(AwsBatchInstancesArchitectureCompatibilityValidator._is_instance_type_format(candidate)).is_equal_to(
        expected_return_value
    )


def test_awsbatch_fsx_validator():
    actual_failures = AwsBatchFsxValidator().execute()
    assert_failure_messages(actual_failures, "FSx is not supported when using AWS Batch as scheduler")
