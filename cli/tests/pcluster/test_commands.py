# Copyright 2013-2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

"""This module provides unit tests for the functions in the pcluster.commands module."""
import pkg_resources
import pytest
from botocore.exceptions import ClientError

import pcluster.utils as utils
from assertpy import assert_that
from pcluster.commands import _create_bucket_with_resources


def test_create_bucket_with_resources_success(mocker):
    """Verify that create_bucket_with_batch_resources behaves as expected."""
    region = "eu-west-1"
    stack_name = "test"

    mocker.patch("pcluster.utils.generate_random_bucket_name", return_value="bucket_name")
    mocker.patch("pcluster.utils.create_s3_bucket")
    upload_resources_artifacts_mock = mocker.patch("pcluster.utils.upload_resources_artifacts")
    delete_s3_bucket_mock = mocker.patch("pcluster.utils.delete_s3_bucket")

    resources_dirs = ["dir1", "dir2"]
    _create_bucket_with_resources(stack_name, region, resources_dirs)
    delete_s3_bucket_mock.assert_not_called()
    upload_resources_artifacts_mock.assert_has_calls(
        [
            mocker.call("bucket_name", root=pkg_resources.resource_filename(utils.__name__, dir))
            for dir in resources_dirs
        ]
    )


def test_create_bucket_with_resources_creation_failure(mocker, caplog):
    """Verify that create_bucket_with_batch_resources behaves as expected in case of bucket creation failure."""
    region = "eu-west-1"
    stack_name = "test"
    bucket_name = stack_name + "-123"
    error = "BucketAlreadyExists"
    client_error = ClientError({"Error": {"Code": error}}, "create_bucket")

    mocker.patch("pcluster.utils.generate_random_bucket_name", return_value=bucket_name)
    mocker.patch("pcluster.utils.create_s3_bucket", side_effect=client_error)
    mocker.patch("pcluster.utils.upload_resources_artifacts")
    delete_s3_bucket_mock = mocker.patch("pcluster.utils.delete_s3_bucket")

    with pytest.raises(ClientError, match=error):
        _create_bucket_with_resources(stack_name, region, ["dir"])
    delete_s3_bucket_mock.assert_not_called()
    assert_that(caplog.text).contains("Unable to create S3 bucket")


def test_create_bucket_with_resources_upload_failure(mocker, caplog):
    """Verify that create_bucket_with_batch_resources behaves as expected in case of upload failure."""
    region = "eu-west-1"
    stack_name = "test"
    bucket_name = stack_name + "-123"
    error = "ExpiredToken"
    client_error = ClientError({"Error": {"Code": error}}, "upload_fileobj")

    mocker.patch("pcluster.utils.generate_random_bucket_name", return_value=bucket_name)
    mocker.patch("pcluster.utils.create_s3_bucket")
    mocker.patch("pcluster.utils.upload_resources_artifacts", side_effect=client_error)
    delete_s3_bucket_mock = mocker.patch("pcluster.utils.delete_s3_bucket")

    with pytest.raises(ClientError, match=error):
        _create_bucket_with_resources(stack_name, region, ["dir"])
    # if resource upload fails we delete the bucket
    delete_s3_bucket_mock.assert_called_with(bucket_name)
    assert_that(caplog.text).contains("Unable to upload cluster resources to the S3 bucket")


def test_create_bucket_with_resources_deletion_failure(mocker, caplog):
    """Verify that create_bucket_with_batch_resources behaves as expected in case of deletion failure."""
    region = "eu-west-1"
    stack_name = "test"
    bucket_name = stack_name + "-123"
    error = "AccessDenied"
    client_error = ClientError({"Error": {"Code": error}}, "delete")

    mocker.patch("pcluster.utils.generate_random_bucket_name", return_value=bucket_name)
    mocker.patch("pcluster.utils.create_s3_bucket")
    # to check bucket deletion we need to trigger a failure in the upload
    mocker.patch("pcluster.utils.upload_resources_artifacts", side_effect=client_error)
    delete_s3_bucket_mock = mocker.patch("pcluster.utils.delete_s3_bucket", side_effect=client_error)

    # force upload failure to trigger a bucket deletion and then check the behaviour when the deletion fails
    with pytest.raises(ClientError, match=error):
        _create_bucket_with_resources(stack_name, region, ["dir"])
    delete_s3_bucket_mock.assert_called_with(bucket_name)
    assert_that(caplog.text).contains("Unable to upload cluster resources to the S3 bucket")
