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
import os

import pytest
from assertpy import assert_that

from pcluster.aws.common import AWSClientError
from pcluster.models.s3_bucket import S3Bucket
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket


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
