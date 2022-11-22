# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import os as os_lib
from datetime import datetime, timedelta

import pytest
from assertpy import assert_that, soft_assertions

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.aws_resources import ImageInfo, InstanceTypeInfo
from pcluster.aws.common import AWSClientError
from pcluster.aws.ec2 import Ec2Client
from pcluster.config.cluster_config import AmiSearchFilters, Tag
from pcluster.constants import OS_TO_IMAGE_NAME_PART_MAP
from pcluster.utils import get_installed_version, to_iso_timestr
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.utils import MockedBoto3Request


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.aws.common.boto3"


@pytest.mark.parametrize(
    "region, free_tier_instance_type, default_instance_type, stub_boto3",
    [
        ("us-east-1", "t2.micro", "t2.micro", True),
        ("eu-north-1", "t3.micro", "t3.micro", True),
        ("us-gov-east-1", None, "t3.micro", True),
    ],
)
@pytest.mark.nomockdefaultinstance
def test_get_default_instance(boto3_stubber, region, free_tier_instance_type, default_instance_type, stub_boto3):
    os_lib.environ["AWS_DEFAULT_REGION"] = region
    if free_tier_instance_type:
        response = {"InstanceTypes": [{"InstanceType": free_tier_instance_type}]}
    else:
        response = {"InstanceTypes": []}
    if stub_boto3:
        mocked_requests = [
            MockedBoto3Request(
                method="describe_instance_types",
                response=response,
                expected_params={
                    "Filters": [
                        {"Name": "free-tier-eligible", "Values": ["true"]},
                        {"Name": "current-generation", "Values": ["true"]},
                    ]
                },
            )
        ]

        boto3_stubber("ec2", mocked_requests)
    assert_that(Ec2Client().get_default_instance_type()).is_equal_to(default_instance_type)


@pytest.mark.parametrize("generate_error", [True, False])
def test_list_instance_types(boto3_stubber, generate_error):
    """Verify that list_instance_types behaves as expected."""
    dummy_message = "dummy error message"
    dummy_instance_types = ["c5.xlarge", "m6g.xlarge"]
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
    if generate_error:
        with pytest.raises(AWSClientError, match=dummy_message):
            Ec2Client().list_instance_types()
    else:
        return_value = Ec2Client().list_instance_types()
        assert_that(return_value).is_equal_to(dummy_instance_types)


@pytest.mark.parametrize(
    "instance_type, supported_architectures, error_message",
    [
        ("t2.micro", ["x86_64", "i386"], None),
        ("a1.medium", ["arm64"], None),
        ("valid.exotic.arch.instance", ["exoticArch"], None),
    ],
)
def test_get_supported_architectures(mocker, instance_type, supported_architectures, error_message):
    """Verify that get_supported_architectures_for_instance_type behaves as expected for various cases."""
    mock_aws_api(mocker)
    get_instance_types_info_patch = mocker.patch(
        "pcluster.aws.ec2.Ec2Client.get_instance_type_info",
        return_value=InstanceTypeInfo({"ProcessorInfo": {"SupportedArchitectures": supported_architectures}}),
    )
    observed_architectures = Ec2Client().get_supported_architectures(instance_type)
    expected_architectures = list(set(supported_architectures) & set(["x86_64", "arm64"]))
    assert_that(observed_architectures).is_equal_to(expected_architectures)

    get_instance_types_info_patch.assert_called_with(instance_type)


@pytest.mark.parametrize(
    "os_part, expected_os",
    [
        ("amzn2-hvm", "alinux2"),
        ("centos7-hvm", "centos7"),
        ("ubuntu-2004-lts-hvm", "ubuntu2004"),
        ("nonexistant-hvm", "linux"),
        ("nonexistant", "linux"),
    ],
)
def test_extract_os_from_official_image_name(os_part, expected_os):
    name = f"aws-parallelcluster-3.0.0-{os_part}-otherstuff"
    os = Ec2Client.extract_os_from_official_image_name(name)
    assert_that(os).is_equal_to(expected_os)


@pytest.mark.parametrize(
    "os, architecture, boto3_response, expected_response, error_message",
    [
        pytest.param(
            None,
            None,
            {
                "Images": [
                    {
                        "Name": "aws-parallelcluster-3.0.0-amzn2-hvm-x86_64-created-earlier",
                        "Architecture": "x86_64",
                        "CreationDate": "2018-11-09T01:21:00.000Z",
                    },
                    {
                        "Name": "aws-parallelcluster-3.0.0-amzn2-hvm-x86_64-created-later",
                        "Architecture": "x86_64",
                        "CreationDate": "2019-11-09T01:21:00.000Z",
                    },
                    {
                        "Name": "aws-parallelcluster-3.0.0-amzn2-hvm-x86_64-deprecated",
                        "Architecture": "x86_64",
                        "CreationDate": "2020-11-09T01:21:00.000Z",
                        "DeprecationTime": "2022-11-09T01:21:00.000Z",
                    },
                    {
                        "Name": "ami-parallelcluster-3.0.0-centos7-hvm-x86_64-other",
                        "Architecture": "x86_64",
                        "CreationDate": "2018-11-09T01:21:00.000Z",
                    },
                ]
            },
            [
                ImageInfo({"Name": "aws-parallelcluster-3.0.0-amzn2-hvm-x86_64-created-later"}),
                ImageInfo({"Name": "ami-parallelcluster-3.0.0-centos7-hvm-x86_64-other"}),
            ],
            None,
            id="test with no filter",
        ),
        pytest.param(
            "alinux2",
            None,
            {
                "Images": [
                    {
                        "Name": "aws-parallelcluster-3.0.0-amzn2-hvm-x86_64-created-earlier",
                        "Architecture": "x86_64",
                        "CreationDate": "2020-10-09T01:21:00.000Z",
                        "DeprecationTime": "2022-11-09T01:21:00.000Z",
                    },
                    {
                        "Name": "aws-parallelcluster-3.0.0-amzn2-hvm-x86_64-created-later",
                        "Architecture": "x86_64",
                        "CreationDate": "2020-11-09T01:21:00.000Z",
                        "DeprecationTime": "2022-11-09T01:21:00.000Z",
                    },
                ]
            },
            [ImageInfo({"Name": "aws-parallelcluster-3.0.0-amzn2-hvm-x86_64-created-later"})],
            None,
            id="test with os",
        ),
        pytest.param(
            None,
            "x86_64",
            {
                "Images": [
                    {
                        "Name": "aws-parallelcluster-3.0.0-amzn2-hvm-x86_64-other",
                        "Architecture": "x86_64",
                        "CreationDate": "2018-11-09T01:21:00.000Z",
                    },
                ]
            },
            [ImageInfo({"Name": "aws-parallelcluster-3.0.0-amzn2-hvm-x86_64-other"})],
            None,
            id="test with architecture",
        ),
        pytest.param(
            "alinux2",
            "x86_64",
            {
                "Images": [
                    {
                        "Name": "aws-parallelcluster-3.0.0-amzn2-hvm-x86_64-other",
                        "Architecture": "x86_64",
                        "CreationDate": "2018-11-09T01:21:00.000Z",
                    },
                ]
            },
            [ImageInfo({"Name": "aws-parallelcluster-3.0.0-amzn2-hvm-x86_64-other"})],
            None,
            id="test with os and architecture",
        ),
        pytest.param("alinux2", "arm64", Exception("error message"), None, "error message", id="test with boto3 error"),
    ],
)
def test_get_official_images(boto3_stubber, os, architecture, boto3_response, expected_response, error_message):
    filter_version = get_installed_version()
    filter_os = OS_TO_IMAGE_NAME_PART_MAP[os] if os else "*"
    filter_arch = architecture or "*"
    expected_params = {
        "Filters": [
            {"Name": "name", "Values": [f"aws-parallelcluster-{filter_version}-{filter_os}-{filter_arch}*"]},
        ],
        "Owners": ["amazon"],
        "IncludeDeprecated": True,
    }
    mocked_requests = [
        MockedBoto3Request(
            method="describe_images",
            expected_params=expected_params,
            response=str(boto3_response) if isinstance(boto3_response, Exception) else boto3_response,
            generate_error=isinstance(boto3_response, Exception),
        )
    ]
    boto3_stubber("ec2", mocked_requests)

    if error_message:
        with pytest.raises(AWSClientError, match=error_message):
            Ec2Client().get_official_images(os, architecture)
    else:
        response = Ec2Client().get_official_images(os, architecture)
        with soft_assertions():
            assert_that(len(response)).is_equal_to(len(expected_response))
            for i in range(len(response)):
                assert_that(response[i].name).is_equal_to(expected_response[i].name)


@pytest.mark.parametrize(
    "os, architecture, filters, boto3_response, error_message",
    [
        (
            "alinux2",
            "arm64",
            None,
            {"Images": [{"ImageId": "ami-00e87074e52e6", "CreationDate": "2018-11-09T01:21:00.000Z"}]},
            None,
        ),
        (
            "alinux2",
            "x86_64",
            AmiSearchFilters(owner="self"),
            {"Images": [{"ImageId": "ami-00e87074e52e6", "CreationDate": "2018-11-09T01:21:00.000Z"}]},
            None,
        ),
        (
            "alinux2",
            "x86_64",
            AmiSearchFilters(owner="self", tags=[Tag("key1", "value1"), Tag("key2", "value2")]),
            {"Images": [{"ImageId": "ami-00e87074e52e6", "CreationDate": "2018-11-09T01:21:00.000Z"}]},
            None,
        ),
        ("alinux2", "arm64", None, Exception("error message"), "error message"),
        ("alinux2", "arm64", None, {"Images": []}, "Cannot find official ParallelCluster AMI"),
        (
            "alinux2",
            "arm64",
            None,
            {
                "Images": [
                    {"ImageId": "ami-older-1", "CreationDate": "2018-11-09T01:21:00.000Z"},
                    {"ImageId": "ami-00e87074e52e6", "CreationDate": "2018-11-09T01:22:00.000Z"},
                    {"ImageId": "ami-older-2", "CreationDate": "2017-11-09T01:21:00.000Z"},
                ]
            },
            None,
        ),
    ],
    ids=["no filtering", "filtering owner", "filtering full", "error from boto3", "empty ami list", "multiple results"],
)
def test_get_official_image_id(boto3_stubber, os, architecture, filters, boto3_response, error_message):
    expected_ami_id = "ami-00e87074e52e6"
    expected_params = {
        "Filters": [
            {"Name": "name", "Values": [f"aws-parallelcluster-{get_installed_version()}-amzn2-hvm-{architecture}*"]},
        ],
        "Owners": [filters.owner if filters and filters.owner else "amazon"],
        "IncludeDeprecated": True,
    }
    if filters and filters.tags:
        expected_params["Filters"].extend([{"Name": f"tag:{tag.key}", "Values": [tag.value]} for tag in filters.tags])
    mocked_requests = [
        MockedBoto3Request(
            method="describe_images",
            expected_params=expected_params,
            response=str(boto3_response) if isinstance(boto3_response, Exception) else boto3_response,
            generate_error=isinstance(boto3_response, Exception),
        )
    ]
    boto3_stubber("ec2", mocked_requests)

    if error_message:
        with pytest.raises(AWSClientError, match=error_message):
            Ec2Client().get_official_image_id(os, architecture, filters)
    else:
        ami_id = Ec2Client().get_official_image_id(os, architecture, filters)
        assert_that(ami_id).is_equal_to(expected_ami_id)


@pytest.mark.parametrize(
    "boto3_response, expected_ami_id",
    [
        (
            {
                "Images": [
                    {
                        "ImageId": "A",
                        "CreationDate": "2018-11-09T01:21:00.000Z",
                        "DeprecationTime": "2022-11-09T01:21:00.000Z",
                    },
                    {
                        "ImageId": "B",
                        "CreationDate": "2019-11-09T01:21:00.000Z",
                        "DeprecationTime": "2022-11-09T01:21:00.000Z",
                    },
                ]
            },
            "B",
        ),
        (
            {
                "Images": [
                    {
                        "ImageId": "A",
                        "CreationDate": "2018-11-09T01:21:00.000Z",
                    },
                    {
                        "ImageId": "B",
                        "CreationDate": "2019-11-09T01:21:00.000Z",
                        "DeprecationTime": "2022-11-09T01:21:00.000Z",
                    },
                ]
            },
            "A",
        ),
        (
            {
                "Images": [
                    {
                        "ImageId": "A",
                        "CreationDate": "2018-11-09T01:21:00.000Z",
                    },
                    {
                        "ImageId": "B",
                        "CreationDate": "2019-11-09T01:21:00.000Z",
                        "DeprecationTime": to_iso_timestr(datetime.now() + timedelta(minutes=5)),
                    },
                ]
            },
            "B",
        ),
    ],
    ids=["both deprecated", "one deprecated", "deprecation in the future"],
)
def test_get_official_image_id_with_deprecation(boto3_stubber, boto3_response, expected_ami_id):
    expected_params = {
        "Filters": [
            {"Name": "name", "Values": [f"aws-parallelcluster-{get_installed_version()}-amzn2-hvm-arm64*"]},
        ],
        "Owners": ["amazon"],
        "IncludeDeprecated": True,
    }
    mocked_requests = [
        MockedBoto3Request(
            method="describe_images",
            expected_params=expected_params,
            response=boto3_response,
            generate_error=False,
        )
    ]
    boto3_stubber("ec2", mocked_requests)

    ami_id = Ec2Client().get_official_image_id("alinux2", "arm64", None)
    assert_that(ami_id).is_equal_to(expected_ami_id)


@pytest.mark.parametrize(
    "snapshot_id, error_message",
    [("snap-1234567890abcdef0", None), ("snap-1234567890abcdef0", "Some error message")],
)
def test_get_ebs_snapshot_info(boto3_stubber, snapshot_id, error_message):
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
        assert_that(Ec2Client().get_ebs_snapshot_info(snapshot_id)).is_equal_to(response)
    elif error_message:
        with pytest.raises(AWSClientError, match=error_message) as clienterror:
            Ec2Client().get_ebs_snapshot_info(snapshot_id)
            assert_that(clienterror.value.code).is_not_equal_to(0)


@pytest.mark.parametrize(
    "error_code, raise_exception",
    [("DryRunOperation", False), ("UnsupportedOperation", True)],
)
def test_run_instances_dryrun(boto3_stubber, error_code, raise_exception):
    """Verify that if run_instance doesn't generate exception if the error code is DryRunOperation."""
    error_message = "fake error message"
    mocked_requests = [
        MockedBoto3Request(
            method="run_instances",
            response=error_message,
            expected_params=None,
            generate_error=True,
            error_code=error_code,
        )
    ]
    boto3_stubber("ec2", mocked_requests)
    kwargs = {"MaxCount": 10, "MinCount": 0, "DryRun": True}
    if raise_exception:
        with pytest.raises(AWSClientError, match=error_message) as clienterror:
            Ec2Client().run_instances(**kwargs)
            assert_that(clienterror.value.code).is_not_equal_to(0)
    else:
        Ec2Client().run_instances(**kwargs)


def get_describe_subnets_mocked_request(subnets, state):
    return MockedBoto3Request(
        method="describe_subnets",
        response={"Subnets": [{"SubnetId": subnet, "State": state} for subnet in subnets]},
        expected_params={"SubnetIds": subnets},
    )


def test_describe_subnets_cache(boto3_stubber):
    # First boto3 call. Nothing has been cached
    subnet = "subnet-123"
    additional_subnet = "subnet-234"
    # The first mocked request and the third are about the same subnet. However, the state of the subnet changes
    # from pending to available. The second mocked request is about another subnet
    mocked_requests = [
        get_describe_subnets_mocked_request([subnet], "pending"),
        get_describe_subnets_mocked_request([additional_subnet], "pending"),
        get_describe_subnets_mocked_request([subnet], "available"),
    ]
    boto3_stubber("ec2", mocked_requests)
    assert_that(AWSApi.instance().ec2.describe_subnets([subnet])[0]["State"]).is_equal_to("pending")

    # Second boto3 call with more subnets. The subnet already cached should not be included in the boto3 call.
    response = AWSApi.instance().ec2.describe_subnets([subnet, additional_subnet])
    assert_that(response).is_length(2)

    # Third boto3 call. The result should be from cache even if the state of the subnet is different
    assert_that(AWSApi.instance().ec2.describe_subnets([subnet])[0]["State"]).is_equal_to("pending")

    # Fourth boto3 call after resetting the AWSApi instance. The latest subnet state should be retrieved from boto3
    AWSApi.reset()
    assert_that(AWSApi.instance().ec2.describe_subnets([subnet])[0]["State"]).is_equal_to("available")


def get_describe_capacity_reservation_mocked_request(capacity_reservations, state):
    return MockedBoto3Request(
        method="describe_capacity_reservations",
        response={
            "CapacityReservations": [
                {"CapacityReservationId": capacity_reservation, "State": state}
                for capacity_reservation in capacity_reservations
            ]
        },
        expected_params={"CapacityReservationIds": capacity_reservations},
    )


def test_describe_capacity_reservations_cache(boto3_stubber):
    # First boto3 call. Nothing has been cached
    capacity_reservation = "cr-123"
    additional_capacity_reservation = "cr-234"
    # The first mocked request and the third are about the same cr. However, the state of the cr changes
    # from pending to available. The second mocked request is about another cr
    mocked_requests = [
        get_describe_capacity_reservation_mocked_request([capacity_reservation], "pending"),
        get_describe_capacity_reservation_mocked_request([additional_capacity_reservation], "pending"),
        get_describe_capacity_reservation_mocked_request([capacity_reservation], "active"),
    ]
    boto3_stubber("ec2", mocked_requests)
    assert_that(AWSApi.instance().ec2.describe_capacity_reservations([capacity_reservation])[0]["State"]).is_equal_to(
        "pending"
    )

    # Second boto3 call with more subnets. The cr already cached should not be included in the boto3 call.
    response = AWSApi.instance().ec2.describe_capacity_reservations(
        [capacity_reservation, additional_capacity_reservation]
    )
    assert_that(response).is_length(2)

    # Third boto3 call. The result should be from cache even if the state of the cr is different
    assert_that(AWSApi.instance().ec2.describe_capacity_reservations([capacity_reservation])[0]["State"]).is_equal_to(
        "pending"
    )

    # Fourth boto3 call after resetting the AWSApi instance. The latest cr state should be retrieved from boto3
    AWSApi.reset()
    assert_that(AWSApi.instance().ec2.describe_capacity_reservations([capacity_reservation])[0]["State"]).is_equal_to(
        "active"
    )


def get_describe_security_groups_mocked_request(security_groups, ip_permissions):
    return MockedBoto3Request(
        method="describe_security_groups",
        response={
            "SecurityGroups": [
                {"GroupId": security_group, "IpPermissions": ip_permissions} for security_group in security_groups
            ]
        },
        expected_params={"GroupIds": security_groups},
    )


def test_describe_security_groups_cache(boto3_stubber):
    # First boto3 call. Nothing has been cached
    security_group = "sg-123"
    additional_security_group = "sg-234"
    # The first mocked request and the third are about the same security group. However, the ip permission of
    # the security group changes from empty to {}. The second mocked request is about another security group
    mocked_requests = [
        get_describe_security_groups_mocked_request([security_group], []),
        get_describe_security_groups_mocked_request([additional_security_group], []),
        get_describe_security_groups_mocked_request([security_group], [{}]),
    ]
    boto3_stubber("ec2", mocked_requests)
    assert_that(AWSApi.instance().ec2.describe_security_groups([security_group])[0]["IpPermissions"]).is_empty()

    # Second boto3 call with more security group.
    # The security group already cached should not be included in the boto3 call.
    response = AWSApi.instance().ec2.describe_security_groups([security_group, additional_security_group])
    assert_that(response).is_length(2)

    # Third boto3 call. The result should be from cache even if the ip permission of the security group is different
    assert_that(AWSApi.instance().ec2.describe_security_groups([security_group])[0]["IpPermissions"]).is_empty()

    # Fourth boto3 call after resetting the AWSApi instance.
    # The latest security group ip permission should be retrieved from boto3
    AWSApi.reset()
    assert_that(AWSApi.instance().ec2.describe_security_groups([security_group])[0]["IpPermissions"]).is_not_empty()
