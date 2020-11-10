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
from pcluster.cli_commands import update
from pcluster.cluster_model import ClusterModel
from pcluster.commands import _setup_bucket_with_resources, _validate_cluster_name
from pcluster.constants import PCLUSTER_NAME_MAX_LENGTH


def _mock_pcluster_config(mocker, scheduler, region, bucket_name=None):
    pcluster_config = mocker.MagicMock()
    pcluster_config.region = region
    cluster_section_mock = mocker.MagicMock()
    cluster_config = {"scheduler": scheduler, "cluster_resource_bucket": bucket_name}
    cluster_section_mock.get_param_value = mocker.MagicMock(side_effect=lambda param: cluster_config[param])
    pcluster_config.get_section = mocker.MagicMock(return_value=cluster_section_mock)

    return pcluster_config


@pytest.mark.parametrize(
    (
        "scheduler",
        "expected_dirs",
        "expect_upload_hit_resources",
        "mock_generated_bucket_name",
        "expected_bucket_name",
        "provided_bucket_name",
        "expected_remove_bucket",
    ),
    [
        ("slurm", ["resources/custom_resources"], True, "bucket", "bucket", None, True),
        ("awsbatch", ["resources/custom_resources", "resources/batch"], False, "bucket", "bucket", None, True),
        ("sge", [], False, None, None, None, True),
        (
            "slurm",
            ["resources/custom_resources"],
            True,
            "bucket",
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
    expect_upload_hit_resources,
    mock_generated_bucket_name,
    expected_bucket_name,
    provided_bucket_name,
    expected_remove_bucket,
):
    """Verify that create_bucket_with_batch_resources behaves as expected."""
    region = "us-east-1"
    mock_artifact_dir = "artifact_dir"
    stack_name = "test-stack"

    mocker.patch(
        "pcluster.utils.generate_random_name_with_prefix", side_effect=[mock_artifact_dir, mock_generated_bucket_name]
    )
    mocker.patch("pcluster.utils.create_s3_bucket")
    check_bucket_mock = mocker.patch("pcluster.utils.check_s3_bucket_exists")
    upload_resources_artifacts_mock = mocker.patch("pcluster.utils.upload_resources_artifacts")
    cleanup_s3_mock = mocker.patch("pcluster.utils.cleanup_s3_resources")
    upload_hit_resources_mock = mocker.patch("pcluster.commands.upload_hit_resources")
    upload_dashboard_resource = mocker.patch("pcluster.commands.upload_dashboard_resource")
    pcluster_config_mock = _mock_pcluster_config(mocker, scheduler, region, bucket_name=provided_bucket_name)

    storage_data = pcluster_config_mock.to_storage()

    bucket_name, artifact_dir, remove_bucket = _setup_bucket_with_resources(
        pcluster_config_mock, storage_data, stack_name, {}
    )

    if provided_bucket_name:
        check_bucket_mock.assert_called_with(provided_bucket_name)
    else:
        check_bucket_mock.assert_not_called()
    cleanup_s3_mock.assert_not_called()
    upload_resources_artifacts_mock.assert_has_calls(
        [
            mocker.call(bucket_name, mock_artifact_dir, root=pkg_resources.resource_filename(utils.__name__, dir))
            for dir in expected_dirs
        ]
    )
    if expect_upload_hit_resources:
        upload_hit_resources_mock.assert_called_with(
            bucket_name, mock_artifact_dir, pcluster_config_mock, storage_data.json_params, {}
        )
    upload_dashboard_resource.assert_called_with(
        bucket_name, mock_artifact_dir, pcluster_config_mock, storage_data.json_params, storage_data.cfn_params
    )
    assert_that(bucket_name).is_equal_to(expected_bucket_name)
    assert_that(artifact_dir).is_equal_to(mock_artifact_dir)
    assert_that(remove_bucket).is_equal_to(expected_remove_bucket)


def test_setup_bucket_with_resources_creation_failure(mocker, caplog):
    """Verify that create_bucket_with_batch_resources behaves as expected in case of bucket creation failure."""
    region = "eu-west-1"
    bucket_name = "parallelcluster-123"
    mock_artifact_dir = "artifact_dir"
    stack_name = "test-stack"
    error = "BucketAlreadyExists"
    client_error = ClientError({"Error": {"Code": error}}, "create_bucket")

    mocker.patch("pcluster.utils.generate_random_name_with_prefix", side_effect=[mock_artifact_dir, bucket_name])
    mocker.patch("pcluster.utils.create_s3_bucket", side_effect=client_error)
    mocker.patch("pcluster.utils.upload_resources_artifacts")
    cleanup_s3_mock = mocker.patch("pcluster.utils.cleanup_s3_resources")

    pcluster_config_mock = _mock_pcluster_config(mocker, "slurm", region)
    storage_data = pcluster_config_mock.to_storage()

    with pytest.raises(ClientError, match=error):
        _setup_bucket_with_resources(pcluster_config_mock, storage_data, stack_name, {})
    cleanup_s3_mock.assert_not_called()
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
    region = "eu-west-1"
    mock_artifact_dir = "artifact_dir"
    stack_name = "test-stack"
    error = "ExpiredToken"
    client_error = ClientError({"Error": {"Code": error}}, "upload_fileobj")

    mocker.patch(
        "pcluster.utils.generate_random_name_with_prefix", side_effect=[mock_artifact_dir, mock_generated_bucket_name]
    )
    mocker.patch("pcluster.utils.create_s3_bucket")
    check_bucket_mock = mocker.patch("pcluster.utils.check_s3_bucket_exists")
    mocker.patch("pcluster.utils.upload_resources_artifacts", side_effect=client_error)
    cleanup_s3_mock = mocker.patch("pcluster.utils.cleanup_s3_resources")

    pcluster_config_mock = _mock_pcluster_config(mocker, "slurm", region, provided_bucket_name)
    storage_data = pcluster_config_mock.to_storage()

    with pytest.raises(ClientError, match=error):
        _setup_bucket_with_resources(pcluster_config_mock, storage_data, stack_name, {})
    if provided_bucket_name:
        check_bucket_mock.assert_called_with(provided_bucket_name)
    else:
        check_bucket_mock.assert_not_called()
    # if resource upload fails we delete the bucket
    cleanup_s3_mock.assert_called_with(expected_bucket_name, mock_artifact_dir, expected_remove_bucket)
    assert_that(caplog.text).contains("Unable to upload cluster resources to the S3 bucket")


def test_setup_bucket_with_resources_deletion_failure(mocker, caplog):
    """Verify that create_bucket_with_batch_resources behaves as expected in case of deletion failure."""
    region = "eu-west-1"
    bucket_name = "parallelcluster-123"
    mock_artifact_dir = "artifact_dir"
    stack_name = "test-stack"
    error = "AccessDenied"
    client_error = ClientError({"Error": {"Code": error}}, "delete")

    mocker.patch("pcluster.utils.generate_random_name_with_prefix", side_effect=[mock_artifact_dir, bucket_name])
    mocker.patch("pcluster.utils.create_s3_bucket")
    # to check bucket deletion we need to trigger a failure in the upload
    mocker.patch("pcluster.utils.upload_resources_artifacts", side_effect=client_error)
    cleanup_s3_mock = mocker.patch("pcluster.utils.delete_s3_artifacts", side_effect=client_error)

    pcluster_config_mock = _mock_pcluster_config(mocker, "slurm", region)
    storage_data = pcluster_config_mock.to_storage()

    # force upload failure to trigger a bucket deletion and then check the behaviour when the deletion fails
    with pytest.raises(ClientError, match=error):
        _setup_bucket_with_resources(pcluster_config_mock, storage_data, stack_name, {})
    cleanup_s3_mock.assert_called_with(bucket_name, mock_artifact_dir)
    assert_that(caplog.text).contains("Unable to upload cluster resources to the S3 bucket")


@pytest.mark.parametrize(
    "base_cluster_model, target_cluster_model, expected_result, expected_message",
    [
        (ClusterModel.SIT, ClusterModel.SIT, True, None),
        (ClusterModel.HIT, ClusterModel.HIT, True, None),
        (ClusterModel.SIT, ClusterModel.HIT, False, "is not compatible with the existing cluster"),
        (ClusterModel.HIT, ClusterModel.SIT, False, "must be converted to the latest format"),
    ],
)
def test_update_failure_on_different_cluster_models(
    mocker, caplog, base_cluster_model, target_cluster_model, expected_result, expected_message
):
    base_config = _mock_pcluster_config(mocker, "slurm", "us-east-1")
    base_config.cluster_model = base_cluster_model
    base_config.cluster_name = "test_cluster"

    target_config = _mock_pcluster_config(mocker, "slurm", "us-east-1")
    target_config.cluster_model = target_cluster_model
    target_config.config_file = "config_file"

    models_check = update._check_cluster_models(base_config, target_config, "default")
    assert_that(models_check).is_equal_to(expected_result)
    if expected_message:
        assert_that(caplog.text).contains(expected_message)
    else:
        assert_that(caplog.text).is_empty()


@pytest.mark.parametrize(
    "cluster_name, should_trigger_error",
    [
        ("ThisClusterNameShouldBeRightSize-ContainAHyphen-AndANumber12", False),
        ("ThisClusterNameShouldBeJustOneCharacterTooLongAndShouldntBeOk", True),
        ("2AClusterCanNotBeginByANumber", True),
        ("ClusterCanNotContainUnderscores_LikeThis", True),
        ("ClusterCanNotContainSpaces LikeThis", True),
    ],
)
def test_validate_cluster_name(cluster_name, should_trigger_error, caplog):
    error_msg = (
        "Error: The cluster name can contain only alphanumeric characters (case-sensitive) and hyphens. "
        "It must start with an alphabetic character and can't be longer than {} characters."
    ).format(PCLUSTER_NAME_MAX_LENGTH)
    if should_trigger_error:
        with pytest.raises(SystemExit):
            _validate_cluster_name(cluster_name)
        assert_that(caplog.text).contains(error_msg)
    else:
        _validate_cluster_name(cluster_name)
        for record in caplog.records:
            assert record.levelname != "CRITICAL"
