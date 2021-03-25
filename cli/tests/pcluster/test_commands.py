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
from pcluster.models.cluster import ClusterActionError
from tests.common.dummy_aws_api import mock_aws_api
from tests.pcluster.models.cluster_dummy_model import dummy_awsbatch_cluster_config, dummy_slurm_cluster_config
from tests.pcluster.test_utils import dummy_cluster


def _mock_cluster(mocker, scheduler, bucket_name=None):
    cluster = dummy_cluster()
    if scheduler == "slurm":
        cluster.config = dummy_slurm_cluster_config(mocker)
        mocker.patch.object(cluster.config, "get_instance_types_data", return_value={})
    else:
        cluster.config = dummy_awsbatch_cluster_config(mocker)

    cluster.config.custom_s3_bucket = bucket_name
    return cluster


@pytest.mark.parametrize(
    (
        "scheduler",
        "expected_dirs",
        "mock_generated_bucket_name",
        "expected_bucket_name",
        "provided_bucket_name",
        "expected_remove_bucket",
    ),
    [
        ("slurm", ["models/../resources/custom_resources"], "bucket", "bucket", None, True),
        (
            "awsbatch",
            ["models/../resources/custom_resources", "models/../resources/batch"],
            "bucket",
            "bucket",
            None,
            True,
        ),
        ("slurm", [], "bucket", "bucket", None, True),
        (
            "slurm",
            ["models/../resources/custom_resources"],
            None,
            "user_provided_bucket",
            "user_provided_bucket",
            False,
        ),
    ],
)
def test_setup_bucket_with_resources_success(
    mocker,
    scheduler,
    expected_dirs,
    mock_generated_bucket_name,
    expected_bucket_name,
    provided_bucket_name,
    expected_remove_bucket,
    aws_api_mock,
):
    """Verify that create_bucket_with_batch_resources behaves as expected."""
    # mock calls for _setup_cluster_bucket
    mock_artifact_dir = "artifact_dir"
    if mock_generated_bucket_name:
        random_name_side_effect = [mock_generated_bucket_name, mock_artifact_dir]
    else:
        random_name_side_effect = [mock_artifact_dir]
    mocker.patch("pcluster.models.cluster.generate_random_name_with_prefix", side_effect=random_name_side_effect)
    mocker.patch("pcluster.models.cluster.create_s3_bucket")
    check_bucket_mock = mocker.patch("pcluster.models.cluster.check_s3_bucket_exists")

    # mock calls from _upload_artifacts
    upload_resources_artifacts_mock = mocker.patch("pcluster.models.cluster.upload_resources_artifacts")

    cluster = _mock_cluster(mocker, scheduler, bucket_name=provided_bucket_name)
    cluster.bucket = cluster._setup_cluster_bucket()
    cluster._upload_artifacts()

    if provided_bucket_name:
        check_bucket_mock.assert_called_with(provided_bucket_name)
    else:
        check_bucket_mock.assert_not_called()
    upload_resources_artifacts_mock.assert_has_calls(
        [
            mocker.call(
                cluster.bucket.name, mock_artifact_dir, root=pkg_resources.resource_filename(utils.__name__, dir)
            )
            for dir in expected_dirs
        ]
    )
    assert_that(cluster.bucket.name).is_equal_to(expected_bucket_name)
    assert_that(cluster.bucket.artifact_directory).is_equal_to(mock_artifact_dir)
    assert_that(cluster.bucket.remove_on_deletion).is_equal_to(expected_remove_bucket)


def test_setup_bucket_with_resources_creation_failure(mocker, caplog, aws_api_mock):
    """Verify that create_bucket_with_batch_resources behaves as expected in case of bucket creation failure."""
    bucket_name = "parallelcluster-123"
    mock_artifact_dir = "artifact_dir"
    error = "BucketAlreadyExists"
    client_error = ClientError({"Error": {"Code": error}}, "create_bucket")

    mocker.patch(
        "pcluster.models.cluster.generate_random_name_with_prefix", side_effect=[bucket_name, mock_artifact_dir]
    )
    mocker.patch("pcluster.models.cluster.create_s3_bucket", side_effect=client_error)
    mocker.patch("pcluster.models.cluster.check_s3_bucket_exists")

    cluster = _mock_cluster(mocker, "slurm")
    with pytest.raises(ClientError, match=error):
        cluster.bucket = cluster._setup_cluster_bucket()
    assert_that(caplog.text).contains("Unable to create S3 bucket")


@pytest.mark.parametrize(
    ("mock_generated_bucket_name", "expected_bucket_name", "provided_bucket_name", "expected_remove_bucket"),
    [
        ("parallelcluster-123", "parallelcluster-123", None, True),
        (None, "user-provided-bucket", "user-provided-bucket", False),
    ],
)
def test_setup_bucket_with_resources_upload_failure(
    mocker, caplog, mock_generated_bucket_name, expected_bucket_name, provided_bucket_name, expected_remove_bucket
):
    """Verify that create_bucket_with_batch_resources behaves as expected in case of upload failure."""
    error = "ExpiredToken"
    cluster_action_error = "Unable to upload cluster resources to the S3 bucket"

    # mock calls for _setup_cluster_bucket
    mock_artifact_dir = "artifact_dir"
    if mock_generated_bucket_name:
        random_name_side_effect = [mock_generated_bucket_name, mock_artifact_dir]
    else:
        random_name_side_effect = [mock_artifact_dir]
    mocker.patch("pcluster.models.cluster.generate_random_name_with_prefix", side_effect=random_name_side_effect)
    mocker.patch("pcluster.models.cluster.create_s3_bucket")
    check_bucket_mock = mocker.patch("pcluster.models.cluster.check_s3_bucket_exists")

    # mock calls from _upload_artifacts
    client_error = ClientError({"Error": {"Code": error}}, "upload_fileobj")
    mocker.patch("pcluster.models.cluster.upload_resources_artifacts", side_effect=client_error)
    mock_aws_api(mocker)
    mocker.patch("common.boto3.s3.S3Client.put_object")

    cluster = _mock_cluster(mocker, "slurm", bucket_name=provided_bucket_name)
    cluster.bucket = cluster._setup_cluster_bucket()

    with pytest.raises(ClusterActionError, match=cluster_action_error):
        cluster._upload_artifacts()
    if provided_bucket_name:
        check_bucket_mock.assert_called_with(provided_bucket_name)
    else:
        check_bucket_mock.assert_not_called()
    assert_that(caplog.text).contains(cluster_action_error)
