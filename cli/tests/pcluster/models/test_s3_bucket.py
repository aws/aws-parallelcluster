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
import json
import os
import textwrap
from unittest.mock import Mock

import pytest
from assertpy import assert_that

from pcluster.aws.common import AWSClientError
from pcluster.models.s3_bucket import S3Bucket, S3FileFormat, S3FileType, format_content
from pcluster.utils import format_arn, get_service_principal
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket, mock_bucket_utils


@pytest.mark.parametrize(
    "region,create_error",
    [
        ("eu-west-1", None),
        ("us-east-1", None),
        ("eu-west-1", AWSClientError("create_bucket", "An error occurred")),
    ],
)
def test_create_s3_bucket(region, create_error, mocker):
    bucket_name = "test"
    expected_params = {"Bucket": bucket_name}
    os.environ["AWS_DEFAULT_REGION"] = region
    if region != "us-east-1":
        # LocationConstraint specifies the region where the bucket will be created.
        # When the region is us-east-1 we are not specifying this parameter because it's the default region.
        expected_params["CreateBucketConfiguration"] = {"LocationConstraint": region}

    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.s3.S3Client.create_bucket", side_effect=create_error)

    mock_bucket(mocker)
    bucket = dummy_cluster_bucket(bucket_name=bucket_name)

    if create_error:
        with pytest.raises(AWSClientError, match="An error occurred"):
            bucket.create_bucket()


@pytest.mark.parametrize(
    "put_bucket_versioning_error, put_bucket_encryption_error, put_bucket_policy_error",
    [
        (None, None, None),
        (AWSClientError("put_bucket_versioning", "An error occurred"), None, None),
        (None, AWSClientError("put_bucket_encryption", "An error occurred"), None),
        (None, None, AWSClientError("put_bucket_policy", "An error occurred")),
    ],
)
def test_configure_s3_bucket(mocker, put_bucket_versioning_error, put_bucket_encryption_error, put_bucket_policy_error):
    mock_aws_api(mocker)
    mock_bucket(mocker)
    bucket = dummy_cluster_bucket()

    mocker.patch("pcluster.aws.s3.S3Client.put_bucket_versioning", side_effect=put_bucket_versioning_error)
    mocker.patch("pcluster.aws.s3.S3Client.put_bucket_encryption", side_effect=put_bucket_encryption_error)
    mocker.patch("pcluster.aws.s3.S3Client.put_bucket_policy", side_effect=put_bucket_policy_error)

    if put_bucket_versioning_error or put_bucket_encryption_error or put_bucket_policy_error:
        with pytest.raises(AWSClientError, match="An error occurred"):
            bucket.configure_s3_bucket()


@pytest.mark.parametrize(
    "region, bucket_name, cluster_name, template_name, expected_url",
    [
        (
            "cn-north-1",
            "bucket-name",
            "cluster-name",
            "file-name",
            "https://bucket-name.s3.cn-north-1.amazonaws.com.cn/cluster-name/templates/file-name",
        ),
        (
            "us-iso-east-1",
            "bucket-name",
            "cluster-name",
            "file-name",
            "https://bucket-name.s3.us-iso-east-1.c2s.ic.gov/cluster-name/templates/file-name",
        ),
        (
            "us-iso-west-1",
            "bucket-name",
            "cluster-name",
            "file-name",
            "https://bucket-name.s3.us-iso-west-1.c2s.ic.gov/cluster-name/templates/file-name",
        ),
        (
            "us-isob-east-1",
            "bucket-name",
            "cluster-name",
            "file-name",
            "https://bucket-name.s3.us-isob-east-1.sc2s.sgov.gov/cluster-name/templates/file-name",
        ),
        (
            "CLASSIC-REGION",
            "bucket-name",
            "cluster-name",
            "file-name",
            "https://bucket-name.s3.CLASSIC-REGION.amazonaws.com/cluster-name/templates/file-name",
        ),
    ],
)
def test_get_cfn_template_url(region, bucket_name, cluster_name, template_name, expected_url):
    os.environ["AWS_DEFAULT_REGION"] = region

    bucket = S3Bucket(
        name=bucket_name,
        stack_name=cluster_name,
        service_name=cluster_name,
        artifact_directory=cluster_name,
    )

    assert_that(bucket.get_cfn_template_url(template_name)).is_equal_to(expected_url)


@pytest.mark.parametrize(
    "region, bucket_name, cluster_name, config_name, expected_url",
    [
        (
            "cn-north-1",
            "bucket-name",
            "cluster-name",
            "file-name",
            "https://bucket-name.s3.cn-north-1.amazonaws.com.cn/cluster-name/configs/file-name",
        ),
        (
            "us-iso-east-1",
            "bucket-name",
            "cluster-name",
            "file-name",
            "https://bucket-name.s3.us-iso-east-1.c2s.ic.gov/cluster-name/configs/file-name",
        ),
        (
            "us-iso-west-1",
            "bucket-name",
            "cluster-name",
            "file-name",
            "https://bucket-name.s3.us-iso-west-1.c2s.ic.gov/cluster-name/configs/file-name",
        ),
        (
            "us-isob-east-1",
            "bucket-name",
            "cluster-name",
            "file-name",
            "https://bucket-name.s3.us-isob-east-1.sc2s.sgov.gov/cluster-name/configs/file-name",
        ),
        (
            "CLASSIC-REGION",
            "bucket-name",
            "cluster-name",
            "file-name",
            "https://bucket-name.s3.CLASSIC-REGION.amazonaws.com/cluster-name/configs/file-name",
        ),
    ],
)
def test_get_config_url(region, bucket_name, cluster_name, config_name, expected_url):
    os.environ["AWS_DEFAULT_REGION"] = region

    bucket = S3Bucket(
        name=bucket_name,
        stack_name=cluster_name,
        service_name=cluster_name,
        artifact_directory=cluster_name,
    )

    assert_that(bucket.get_config_url(config_name)).is_equal_to(expected_url)


@pytest.mark.parametrize(
    "region, bucket_name, cluster_name, resource_name, expected_url",
    [
        (
            "cn-north-1",
            "bucket-name",
            "cluster-name",
            "file-name",
            "https://bucket-name.s3.cn-north-1.amazonaws.com.cn/cluster-name/custom_resources/file-name",
        ),
        (
            "us-iso-east-1",
            "bucket-name",
            "cluster-name",
            "file-name",
            "https://bucket-name.s3.us-iso-east-1.c2s.ic.gov/cluster-name/custom_resources/file-name",
        ),
        (
            "us-iso-west-1",
            "bucket-name",
            "cluster-name",
            "file-name",
            "https://bucket-name.s3.us-iso-west-1.c2s.ic.gov/cluster-name/custom_resources/file-name",
        ),
        (
            "us-isob-east-1",
            "bucket-name",
            "cluster-name",
            "file-name",
            "https://bucket-name.s3.us-isob-east-1.sc2s.sgov.gov/cluster-name/custom_resources/file-name",
        ),
        (
            "CLASSIC-REGION",
            "bucket-name",
            "cluster-name",
            "file-name",
            "https://bucket-name.s3.CLASSIC-REGION.amazonaws.com/cluster-name/custom_resources/file-name",
        ),
    ],
)
def test_get_resource_url(region, bucket_name, cluster_name, resource_name, expected_url):
    os.environ["AWS_DEFAULT_REGION"] = region

    bucket = S3Bucket(
        name=bucket_name,
        stack_name=cluster_name,
        service_name=cluster_name,
        artifact_directory=cluster_name,
    )

    assert_that(bucket.get_resource_url(resource_name)).is_equal_to(expected_url)


@pytest.mark.parametrize(
    "content, s3_file_format, expected_output",
    [
        (
            {
                "A": {
                    "A1": "X",
                    "A2": "Y",
                },
                "B": {"B1": "M"},
            },
            S3FileFormat.YAML,
            textwrap.dedent(
                """\
                A:
                  A1: X
                  A2: Y
                B:
                  B1: M
                """
            ),
        ),
        (
            {
                "A": {
                    "A1": "X",
                    "A2": "Y",
                },
                "B": {"B1": "M"},
            },
            S3FileFormat.JSON,
            '{"A": {"A1": "X", "A2": "Y"}, "B": {"B1": "M"}}',
        ),
        (
            {
                "A": {
                    "A1": "X",
                    "A2": "Y",
                },
                "B": {"B1": "M"},
            },
            S3FileFormat.MINIFIED_JSON,
            '{"A":{"A1":"X","A2":"Y"},"B":{"B1":"M"}}',
        ),
        (
            {
                "A": {
                    "A1": "X",
                    "A2": "Y",
                },
                "B": {"B1": "M"},
            },
            None,
            {"A": {"A1": "X", "A2": "Y"}, "B": {"B1": "M"}},
        ),
    ],
)
def test_format_content(content, s3_file_format, expected_output):
    formatted_content = format_content(content=content, s3_file_format=s3_file_format)
    assert_that(formatted_content).is_equal_to(expected_output)
    assert_that(formatted_content).is_type_of(type(expected_output))


@pytest.mark.parametrize(
    "content, file_name, file_type, s3_file_format, expected_object_key, expected_object_body",
    [
        (
            {"Test": "Content"},
            "test_file_name",
            S3FileType.ASSETS,
            S3FileFormat.YAML,
            "assets/test_file_name",
            "Test: Content\n",
        )
    ],
)
def test_upload_file(mocker, content, file_name, file_type, s3_file_format, expected_object_key, expected_object_body):
    mock_aws_api(mocker)
    mock_bucket(mocker)

    bucket_name = "test-bucket"
    artifact_directory = "pcluster_artifact_directory"
    bucket = dummy_cluster_bucket(bucket_name=bucket_name, artifact_directory=artifact_directory)
    s3_put_object_patch = mocker.patch("pcluster.aws.s3.S3Client.put_object")

    bucket.upload_file(content, file_name, file_type, s3_file_format)

    s3_put_object_patch.assert_called_once_with(
        bucket_name=bucket_name,
        body=expected_object_body,
        key=f"{artifact_directory}/{expected_object_key}",
    )


def test_get_bucket_policy_for_cloudwatch_logs(mocker):
    mock_aws_api(mocker)
    mock_bucket(mocker)
    mock_bucket_utils(mocker)

    bucket = S3Bucket(
        service_name="test-service",
        stack_name="test-stack",
        artifact_directory="test-artifact-directory",
    )

    partition = "fake_partition"
    region = "fake-region"
    account_id = "fake-id"
    bucket_name = bucket.name

    bucket_arn = format_arn(partition, "s3", "", "", bucket_name)
    bucket_arn_with_wildcard = f"{bucket_arn}/*"
    logs_service_principal = get_service_principal(
        service_name="logs", partition=partition, region=region, regional=True
    )

    log_group_arns = [
        format_arn(partition, "logs", region, account_id, "log-group:/aws/parallelcluster/*"),
        format_arn(partition, "logs", region, account_id, "log-group:/aws/imagebuilder/*"),
    ]

    policy_statements = bucket._get_bucket_policy_for_cloudwatch_logs()

    assert_that(policy_statements).is_length(3)

    expected_policy_statements = [
        {
            "Sid": "AllowReadBucketAclForExportLogs",
            "Action": "s3:GetBucketAcl",
            "Effect": "Allow",
            "Resource": bucket_arn,
            "Principal": {"Service": logs_service_principal},
            "Condition": {
                "StringEquals": {"aws:SourceAccount": account_id},
                "ArnLike": {
                    "aws:SourceArn": log_group_arns,
                },
            },
        },
        {
            "Sid": "AllowPutObjectForExportLogs",
            "Action": "s3:PutObject",
            "Effect": "Allow",
            "Resource": bucket_arn_with_wildcard,
            "Principal": {"Service": logs_service_principal},
            "Condition": {
                "StringEquals": {
                    "s3:x-amz-acl": "bucket-owner-full-control",
                    "aws:SourceAccount": account_id,
                },
                "ArnLike": {
                    "aws:SourceArn": log_group_arns,
                },
            },
        },
        {
            "Sid": "DenyPutObjectOnReservedPath",
            "Action": "s3:PutObject",
            "Effect": "Deny",
            "Resource": f"{bucket_arn}/parallelcluster/*",
            "Principal": {"Service": logs_service_principal},
        },
    ]
    assert_that(policy_statements).is_equal_to(expected_policy_statements)


def test_generate_bucket_policy(mocker):
    """Test _generate_bucket_policy method."""
    mock_aws_api(mocker)
    mock_bucket(mocker)
    mock_bucket_utils(mocker)

    bucket = S3Bucket(
        service_name="test-service",
        stack_name="test-stack",
        artifact_directory="test-artifact-directory",
    )
    bucket_name = bucket.name

    # Mock _get_bucket_policy_for_cloudwatch_logs
    mock_logs_policy_statements = [
        {"Sid": "MockStatement1", "Action": "s3:MockAction1"},
        {"Sid": "MockStatement2", "Action": "s3:MockAction2"},
    ]
    mocker.patch(
        "pcluster.models.s3_bucket.S3Bucket._get_bucket_policy_for_cloudwatch_logs",
        return_value=mock_logs_policy_statements,
    )

    # Expected values
    partition = "fake_partition"
    bucket_arn = format_arn(partition, "s3", "", "", bucket_name)
    bucket_arn_with_wildcard = f"{bucket_arn}/*"

    bucket_policy = bucket._generate_bucket_policy()

    # Verify bucket_policy
    assert_that(bucket_policy["Version"]).is_equal_to("2012-10-17")
    assert_that(bucket_policy).contains("Statement")
    statements = bucket_policy["Statement"]

    # There should be one DenyHTTP policy and the mocked logs_policy_statements
    assert_that(statements).is_length(1 + len(mock_logs_policy_statements))

    # Verify DenyHTTP policy
    deny_http_statement = statements[0]
    expected_deny_http_statement = {
        "Sid": "AllowSSLRequestsOnly",
        "Effect": "Deny",
        "Principal": "*",
        "Action": "s3:*",
        "Resource": [bucket_arn, bucket_arn_with_wildcard],
        "Condition": {"Bool": {"aws:SecureTransport": "false"}},
    }
    assert_that(deny_http_statement).is_equal_to(expected_deny_http_statement)

    # Verify the mocked logs_policy_statements is contained
    assert_that(statements[1:]).is_equal_to(mock_logs_policy_statements)


@pytest.mark.parametrize(
    (
        "head_object_side_effect",
        "get_object_side_effect",
        "get_object_return_value",
        "expected_result",
        "expected_exception",
    ),
    [
        (
            pytest.param(
                None,
                None,
                {
                    "Body": Mock(
                        read=Mock(
                            return_value=json.dumps({"bootstrapped_features": ["basic", "export-logs"]}).encode("utf-8")
                        )
                    )
                },
                True,
                None,
                id="The bootstrap file exists, content is in the new format, and contains all required features",
            )
        ),
        (
            pytest.param(
                None,
                None,
                {
                    "Body": Mock(
                        read=Mock(return_value=json.dumps({"bootstrapped_features": ["basic"]}).encode("utf-8"))
                    )
                },
                False,
                None,
                id="The bootstrap file exists, content is in the new format, but some required features are missing",
            )
        ),
        (
            pytest.param(
                None,
                None,
                {"Body": Mock(read=Mock(return_value="bucket is configured successfully.".encode("utf-8")))},
                False,
                None,
                id="The bootstrap file exists, content is in old format (not JSON string)",
            )
        ),
        (
            pytest.param(
                AWSClientError(function_name="head_object", message="Not Found", error_code="404"),
                None,
                None,
                False,
                None,
                id="The bootstrap file does not exist (head_object throws 404 error)",
            )
        ),
        (
            pytest.param(
                None,
                AWSClientError(function_name="get_object", message="Access Denied", error_code="403"),
                None,
                None,
                AWSClientError,
                id="get_object throws AWSClientError (not a 404 error)",
            )
        ),
        (
            pytest.param(
                None,
                None,
                {"Body": Mock(read=Mock(return_value="{invalid json}".encode("utf-8")))},
                False,
                None,
                id="The bootstrap file content cannot be parsed as JSON",
            )
        ),
    ],
)
def test_check_bucket_is_bootstrapped(
    mocker,
    head_object_side_effect,
    get_object_side_effect,
    get_object_return_value,
    expected_result,
    expected_exception,
):
    mock_aws_api(mocker)
    mock_bucket(mocker)
    mock_bucket_utils(mocker)
    bucket = S3Bucket(
        service_name="test-service",
        stack_name="test-stack",
        artifact_directory="test-artifact-directory",
    )

    mocker.patch("pcluster.aws.s3.S3Client.head_object", side_effect=head_object_side_effect)

    mocker.patch(
        "pcluster.aws.s3.S3Client.get_object",
        side_effect=get_object_side_effect,
        return_value=get_object_return_value,
    )

    if expected_exception:
        with pytest.raises(expected_exception):
            bucket.check_bucket_is_bootstrapped()
    else:
        result = bucket.check_bucket_is_bootstrapped()
        assert_that(result).is_equal_to(expected_result)
