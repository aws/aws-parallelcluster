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
from pcluster.models.s3_bucket import S3Bucket


def dummy_cluster_bucket(
    bucket_name="parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
    artifact_directory="parallelcluster/clusters/dummy-cluster-randomstring123",
    service_name="dummy-cluster",
):
    """Generate dummy cluster bucket."""
    return S3Bucket(
        name=bucket_name,
        stack_name=f"parallelcluster-{service_name}",
        service_name=service_name,
        artifact_directory=artifact_directory,
    )


def dummy_imagebuilder_bucket(
    bucket_name="parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
    artifact_directory="parallelcluster/imagebuilders/dummy-image-randomstring123",
    service_name="dummy-image",
):
    """Generate dummy imagebuilder bucket."""
    return S3Bucket(
        name=bucket_name,
        stack_name=service_name,
        service_name=service_name,
        artifact_directory=artifact_directory,
    )


def mock_bucket(
    mocker,
):
    """Mock cluster bucket initialization."""
    mocker.patch("pcluster.models.s3_bucket.get_partition", return_value="fake_partition")
    mocker.patch("pcluster.models.s3_bucket.get_region", return_value="fake-region")
    mocker.patch("pcluster.aws.sts.StsClient.get_account_id", return_value="fake-id")


def mock_bucket_utils(
    mocker,
    bucket_name="parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
    root_service_dir="dummy-cluster-randomstring123",
    check_bucket_exists_side_effect=None,
    create_bucket_side_effect=None,
    configure_bucket_side_effect=None,
):
    get_bucket_name_mock = mocker.patch("pcluster.models.s3_bucket.S3Bucket.get_bucket_name", return_value=bucket_name)
    create_bucket_mock = mocker.patch(
        "pcluster.models.s3_bucket.S3Bucket.create_bucket", side_effect=create_bucket_side_effect
    )
    check_bucket_exists_mock = mocker.patch(
        "pcluster.models.s3_bucket.S3Bucket.check_bucket_exists", side_effect=check_bucket_exists_side_effect
    )
    mocker.patch("pcluster.models.s3_bucket.S3Bucket.generate_s3_bucket_hash_suffix", return_value=root_service_dir)
    configure_s3_bucket_mock = mocker.patch(
        "pcluster.models.s3_bucket.S3Bucket.configure_s3_bucket", side_effect=configure_bucket_side_effect
    )
    mock_dict = {
        "get_bucket_name": get_bucket_name_mock,
        "create_bucket": create_bucket_mock,
        "check_bucket_exists": check_bucket_exists_mock,
        "configure_s3_bucket": configure_s3_bucket_mock,
    }
    return mock_dict


def mock_bucket_object_utils(
    mocker,
    upload_config_side_effect=None,
    get_config_side_effect=None,
    upload_template_side_effect=None,
    upload_asset_side_effect=None,
    get_template_side_effect=None,
    upload_resources_side_effect=None,
    delete_s3_artifacts_side_effect=None,
    upload_bootstrapped_file_side_effect=None,
    check_bucket_is_bootstrapped_side_effect=None,
):
    # mock call from config
    fake_config = {"Image": "image"}
    upload_config_mock = mocker.patch(
        "pcluster.models.s3_bucket.S3Bucket.upload_config", side_effect=upload_config_side_effect
    )
    get_config_mock = mocker.patch(
        "pcluster.models.s3_bucket.S3Bucket.get_config", return_value=fake_config, side_effect=get_config_side_effect
    )

    # mock call from template
    fake_template = {"Resources": "fake_resource"}
    upload_cfn_template_mock = mocker.patch(
        "pcluster.models.s3_bucket.S3Bucket.upload_cfn_template", side_effect=upload_template_side_effect
    )
    upload_cfn_asset_mock = mocker.patch(
        "pcluster.models.s3_bucket.S3Bucket.upload_cfn_asset", side_effect=upload_asset_side_effect
    )
    get_cfn_template_mock = mocker.patch(
        "pcluster.models.s3_bucket.S3Bucket.get_cfn_template",
        return_value=fake_template,
        side_effect=get_template_side_effect,
    )

    # mock calls from custom resources
    upload_resources_mock = mocker.patch(
        "pcluster.models.s3_bucket.S3Bucket.upload_resources", side_effect=upload_resources_side_effect
    )

    # mock delete_s3_artifacts
    delete_s3_artifacts_mock = mocker.patch(
        "pcluster.models.s3_bucket.S3Bucket.delete_s3_artifacts", side_effect=delete_s3_artifacts_side_effect
    )

    # mock bootstrapped_file
    upload_bootstrapped_file_mock = mocker.patch(
        "pcluster.models.s3_bucket.S3Bucket.upload_bootstrapped_file", side_effect=upload_bootstrapped_file_side_effect
    )
    check_bucket_is_bootstrapped_mock = mocker.patch(
        "pcluster.models.s3_bucket.S3Bucket.check_bucket_is_bootstrapped",
        side_effect=check_bucket_is_bootstrapped_side_effect,
    )

    mock_dict = {
        "upload_config": upload_config_mock,
        "get_config": get_config_mock,
        "upload_cfn_template": upload_cfn_template_mock,
        "upload_cfn_asset": upload_cfn_asset_mock,
        "get_cfn_template": get_cfn_template_mock,
        "upload_resources": upload_resources_mock,
        "delete_s3_artifacts": delete_s3_artifacts_mock,
        "upload_bootstrapped_file": upload_bootstrapped_file_mock,
        "check_bucket_is_bootstrapped": check_bucket_is_bootstrapped_mock,
    }

    return mock_dict
