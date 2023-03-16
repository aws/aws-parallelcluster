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
import pytest
from assertpy import assert_that

from pcluster.aws.common import AWSClientError
from pcluster.models.cluster import ClusterActionError, ClusterStack
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.config.dummy_cluster_config import dummy_awsbatch_cluster_config, dummy_slurm_cluster_config
from tests.pcluster.models.dummy_s3_bucket import mock_bucket, mock_bucket_object_utils, mock_bucket_utils
from tests.pcluster.test_utils import dummy_cluster


def _mock_cluster(
    mocker,
    scheduler,
    bucket_name="parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
    artifact_directory="parallelcluster/clusters/dummy-cluster-randomstring123",
    describe_stack_side_effect=None,
):
    if bucket_name:
        stack_data = {
            "Parameters": [
                {"ParameterKey": "ArtifactS3RootDirectory", "ParameterValue": artifact_directory},
                {"ParameterKey": "ResourcesS3Bucket", "ParameterValue": bucket_name},
            ]
        }
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", return_value=stack_data)
        cluster = dummy_cluster(stack=ClusterStack(stack_data))
    else:
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", side_effect=describe_stack_side_effect)
        cluster = dummy_cluster()

    if scheduler == "slurm":
        cluster.config = dummy_slurm_cluster_config(mocker)
        mocker.patch.object(cluster.config, "get_instance_types_data", return_value={})
    else:
        cluster.config = dummy_awsbatch_cluster_config(mocker)

    return cluster


@pytest.mark.parametrize(
    (
        "scheduler",
        "cluster_name",
        "expected_config",
        "expected_template",
        "expected_asset",
        "expected_dirs",
        "mock_generated_bucket_name",
        "expected_bucket_name",
        "provided_bucket_name",
    ),
    [
        (
            "slurm",
            "cluster1",
            "dummy_config1",
            "dummy_template1",
            "dummy_asset1",
            ["models/../resources/custom_resources"],
            "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
            "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
            None,
        ),
        (
            "awsbatch",
            "cluster2",
            "dummy_config2",
            "dummy_template2",
            "dummy_asset2",
            ["models/../resources/custom_resources", "models/../resources/batch"],
            "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
            "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
            None,
        ),
        (
            "slurm",
            "cluster3",
            "dummy_config3",
            "dummy_template3",
            "dummy_asset3",
            [],
            "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
            "parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
            None,
        ),
        (
            "slurm",
            "cluster4",
            "dummy_config4",
            "dummy_template4",
            "dummy_asset4",
            ["models/../resources/custom_resources"],
            None,
            "user_provided_bucket",
            "user_provided_bucket",
        ),
    ],
)
def test_setup_bucket_with_resources_success(
    mocker,
    scheduler,
    cluster_name,
    expected_config,
    expected_template,
    expected_asset,
    expected_dirs,
    mock_generated_bucket_name,
    expected_bucket_name,
    provided_bucket_name,
):
    """Verify that create_bucket_with_batch_resources behaves as expected."""
    # mock calls for bucket property in cluster object
    artifact_dir = f"parallelcluster/clusters/{cluster_name}-abc123"

    mock_aws_api(mocker)

    # mock bucket initialization
    mock_bucket(mocker)

    # mock bucket object utils
    mock_dict = mock_bucket_object_utils(mocker)
    upload_config_mock = mock_dict.get("upload_config")
    upload_template_mock = mock_dict.get("upload_cfn_template")
    upload_asset_mock = mock_dict.get("upload_cfn_asset")
    upload_custom_resources_mock = mock_dict.get("upload_resources")
    # mock bucket utils
    check_bucket_mock = mock_bucket_utils(mocker, root_service_dir=f"{cluster_name}-abc123")["check_bucket_exists"]

    if provided_bucket_name:
        cluster = _mock_cluster(mocker, scheduler, bucket_name=provided_bucket_name, artifact_directory=artifact_dir)
        cluster.config.custom_s3_bucket = provided_bucket_name
    else:
        cluster = _mock_cluster(
            mocker, scheduler, bucket_name=mock_generated_bucket_name, artifact_directory=artifact_dir
        )

    cluster.bucket.upload_config(expected_config, "fake_config_name")
    cluster.bucket.upload_cfn_template(expected_template, "fake_template_name")
    cluster.bucket.upload_cfn_asset(expected_asset, "fake_asset_name")
    for dir in expected_dirs:
        cluster.bucket.upload_resources(dir)

    check_bucket_mock.assert_called_with()

    # assert upload has been called
    upload_config_mock.assert_called_with(expected_config, "fake_config_name")
    upload_template_mock.assert_called_with(expected_template, "fake_template_name")
    upload_asset_mock.assert_called_with(expected_asset, "fake_asset_name")
    upload_custom_resources_mock.assert_has_calls([mocker.call(dir) for dir in expected_dirs])

    # assert bucket properties
    assert_that(cluster.bucket.name).is_equal_to(expected_bucket_name)
    assert_that(cluster.bucket.artifact_directory).is_equal_to(artifact_dir)
    assert_that(cluster.bucket._root_directory).is_equal_to("parallelcluster")


@pytest.mark.parametrize(
    ("provided_bucket_name", "check_bucket_exists_error", "create_bucket_error", "cluster_action_error"),
    [
        (
            "parallelcluster-123",
            AWSClientError(function_name="head_bucket", message="Not Found", error_code="404"),
            None,
            "Unable to access config-specified S3 bucket parallelcluster-123.",
        ),
        (
            None,
            AWSClientError(function_name="head_bucket", message="Not Found", error_code="404"),
            AWSClientError(function_name="create_bucket", message="BucketReachLimit"),
            "BucketReachLimit",
        ),
    ],
)
def test_setup_bucket_with_resources_creation_failure(
    mocker, provided_bucket_name, check_bucket_exists_error, create_bucket_error, cluster_action_error
):
    """Verify that create_bucket_with_batch_resources behaves as expected in case of bucket initialization failure."""
    mock_aws_api(mocker)

    # mock bucket initialization
    mock_bucket(mocker)

    if provided_bucket_name:
        # mock bucket utils
        mock_bucket_utils(mocker, check_bucket_exists_side_effect=check_bucket_exists_error)
        cluster = _mock_cluster(mocker, "slurm", bucket_name=provided_bucket_name)
        cluster.config.custom_s3_bucket = provided_bucket_name
    else:
        # mock bucket utils
        mock_bucket_utils(
            mocker,
            create_bucket_side_effect=create_bucket_error,
            check_bucket_exists_side_effect=check_bucket_exists_error,
        )
        cluster = _mock_cluster(mocker, "slurm")

    # mock bucket object utils
    mocker.patch("pcluster.models.s3_bucket.S3Bucket.check_bucket_is_bootstrapped")

    # assert failures
    if provided_bucket_name:
        with pytest.raises(ClusterActionError, match=cluster_action_error):
            bucket_name = cluster.bucket.name
            assert_that(bucket_name).is_equal_to(provided_bucket_name)
    else:
        with pytest.raises(ClusterActionError, match=cluster_action_error):
            bucket_name = cluster.bucket.name
            assert_that(bucket_name).is_equal_to("parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete")


@pytest.mark.parametrize(
    (
        "check_bucket_is_bootstrapped_error",
        "bucket_configure_error",
        "upload_bootstrapped_file_error",
        "cluster_action_error",
    ),
    [
        (
            AWSClientError(function_name="head_object", message="No object", error_code="404"),
            AWSClientError(function_name="put_bucket_versioning", message="No put bucket versioning policy"),
            None,
            "Unable to initialize s3 bucket. No put bucket versioning policy",
        ),
        (
            AWSClientError(function_name="head_object", message="NoSuchBucket", error_code="403"),
            None,
            None,
            "NoSuchBucket",
        ),
        (
            AWSClientError(function_name="head_object", message="No object", error_code="404"),
            None,
            AWSClientError(function_name="put_object", message="No put object policy"),
            "No put object policy",
        ),
    ],
)
def test_setup_bucket_with_bucket_configuration_failure(
    mocker,
    check_bucket_is_bootstrapped_error,
    bucket_configure_error,
    upload_bootstrapped_file_error,
    cluster_action_error,
):
    """Verify that create_bucket_with_batch_resources behaves as expected in case of bucket configuration failure."""
    mock_aws_api(mocker)

    # mock bucket initialization
    mock_bucket(mocker)

    # mock bucket utils
    mock_bucket_utils(mocker, configure_bucket_side_effect=bucket_configure_error)
    cluster = _mock_cluster(mocker, "slurm")

    # mock bucket object utils
    mock_bucket_object_utils(
        mocker,
        check_bucket_is_bootstrapped_side_effect=check_bucket_is_bootstrapped_error,
        upload_bootstrapped_file_side_effect=upload_bootstrapped_file_error,
    )

    with pytest.raises(ClusterActionError, match=cluster_action_error):
        bucket_name = cluster.bucket.name
        assert_that(bucket_name).is_equal_to("parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete")


@pytest.mark.parametrize(
    ("cluster_name", "scheduler", "mock_generated_bucket_name", "expected_bucket_name", "provided_bucket_name"),
    [
        ("cluster1", "slurm", "parallelcluster-123", "parallelcluster-123", None),
        ("cluster2", "aws_batch", None, "user-provided-bucket", "user-provided-bucket"),
    ],
)
def test_setup_bucket_with_resources_upload_failure(
    mocker, cluster_name, scheduler, mock_generated_bucket_name, expected_bucket_name, provided_bucket_name
):
    """Verify that create_bucket_with_batch_resources behaves as expected in case of upload failure."""
    upload_config_cluster_action_error = "Unable to upload cluster config to the S3 bucket"
    upload_resource_cluster_action_error = "Unable to upload cluster resources to the S3 bucket"
    upload_awsclient_error = AWSClientError(function_name="put_object", message="Unable to put file to the S3 bucket")
    upload_fileobj_awsclient_error = AWSClientError(
        function_name="upload_fileobj", message="Unable to upload file to the S3 bucket"
    )

    mock_aws_api(mocker)

    # mock bucket initialization
    mock_bucket(mocker)

    # mock bucket utils
    check_bucket_mock = mock_bucket_utils(
        mocker,
        bucket_name=provided_bucket_name,
        root_service_dir=f"{cluster_name}-abc123",
    )["check_bucket_exists"]

    # mock bucket object utils
    mock_bucket_object_utils(
        mocker,
        upload_config_side_effect=upload_awsclient_error,
        upload_template_side_effect=upload_awsclient_error,
        upload_resources_side_effect=upload_fileobj_awsclient_error,
    )

    if provided_bucket_name:
        cluster = _mock_cluster(mocker, scheduler, provided_bucket_name)
        cluster.config.cluster_s3_bucket = provided_bucket_name
    else:
        cluster = _mock_cluster(mocker, scheduler)

    with pytest.raises(ClusterActionError, match=upload_config_cluster_action_error):
        cluster._upload_config()

    with pytest.raises(ClusterActionError, match=upload_resource_cluster_action_error):
        cluster._upload_artifacts()

    check_bucket_mock.assert_called_with()
