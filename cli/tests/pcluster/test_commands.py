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
from assertpy import assert_that
from botocore.exceptions import ClientError

import pcluster.utils as utils
from pcluster.commands import _create_bucket_with_resources


def _mock_pcluster_config(mocker, scheduler, region, hit_template_url):
    pcluster_config = mocker.MagicMock()
    pcluster_config.region = region
    cluster_section_mock = mocker.MagicMock()
    cluster_config = {
        "scheduler": scheduler,
        "hit_template_url": hit_template_url,
    }
    cluster_section_mock.get_param_value = mocker.MagicMock(side_effect=lambda param: cluster_config[param])
    pcluster_config.get_section = mocker.MagicMock(return_value=cluster_section_mock)

    return pcluster_config


@pytest.mark.parametrize(
    "scheduler, expected_dirs, expect_upload_hit_resources, expected_bucket_name",
    [
        ("slurm", ["resources/custom_resources"], True, "bucket"),
        ("awsbatch", ["resources/custom_resources", "resources/batch"], False, "bucket"),
        ("sge", [], False, None),
    ],
)
def test_create_bucket_with_resources_success(
    mocker, scheduler, expected_dirs, expect_upload_hit_resources, expected_bucket_name
):
    """Verify that create_bucket_with_batch_resources behaves as expected."""
    stack_name = "test"
    region = "us-east-1"
    hit_template_url = "s3://{region}-aws-parallelcluster/templates/aws-parallelcluster-{version}.cfn.json"

    mocker.patch("pcluster.utils.generate_random_bucket_name", return_value=expected_bucket_name)
    mocker.patch("pcluster.utils.create_s3_bucket")
    upload_resources_artifacts_mock = mocker.patch("pcluster.utils.upload_resources_artifacts")
    delete_s3_bucket_mock = mocker.patch("pcluster.utils.delete_s3_bucket")
    upload_hit_resources_mock = mocker.patch("pcluster.commands._upload_hit_resources")
    pcluster_config_mock = _mock_pcluster_config(mocker, scheduler, region, hit_template_url)

    storage_data = pcluster_config_mock.to_storage()

    bucket_name = _create_bucket_with_resources(stack_name, pcluster_config_mock, storage_data.json_params)

    delete_s3_bucket_mock.assert_not_called()
    upload_resources_artifacts_mock.assert_has_calls(
        [mocker.call(bucket_name, root=pkg_resources.resource_filename(utils.__name__, dir)) for dir in expected_dirs]
    )
    if expect_upload_hit_resources:
        upload_hit_resources_mock.assert_called_with(bucket_name, pcluster_config_mock, storage_data.json_params)
    assert_that(bucket_name).is_equal_to(expected_bucket_name)


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

    pcluster_config_mock = _mock_pcluster_config(mocker, "slurm", region, None)
    storage_data = pcluster_config_mock.to_storage()

    with pytest.raises(ClientError, match=error):
        _create_bucket_with_resources(stack_name, pcluster_config_mock, storage_data.json_params)
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

    pcluster_config_mock = _mock_pcluster_config(mocker, "slurm", region, None)
    storage_data = pcluster_config_mock.to_storage()

    with pytest.raises(ClientError, match=error):
        _create_bucket_with_resources(stack_name, pcluster_config_mock, storage_data.json_params)
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

    pcluster_config_mock = _mock_pcluster_config(mocker, "slurm", region, None)
    storage_data = pcluster_config_mock.to_storage()

    # force upload failure to trigger a bucket deletion and then check the behaviour when the deletion fails
    with pytest.raises(ClientError, match=error):
        _create_bucket_with_resources(stack_name, pcluster_config_mock, storage_data.json_params)
    delete_s3_bucket_mock.assert_called_with(bucket_name)
    assert_that(caplog.text).contains("Unable to upload cluster resources to the S3 bucket")
