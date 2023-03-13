#  Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import pytest

from pcluster.templates.cdk_assets_manager import CDKAssetsManager, ClusterAssetFile
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket, mock_bucket_object_utils


@pytest.mark.parametrize(
    "file_assets, asset_content",
    [
        (
            [
                ClusterAssetFile(
                    path="asset_path",
                    id="asset_logical_id",
                    s3_bucket_parameter="asset_s3_bucket",
                    s3_key_parameter="asset_s3_key",
                    artifact_hash_parameter="asset_hash_parameter",
                )
            ],
            "asset_content",
        )
    ],
)
def test_upload_assets(mocker, mock_cloud_assembly, file_assets, asset_content):
    mocker.patch("pcluster.templates.cdk_assets_manager.load_yaml_dict", return_value=asset_content)
    cluster_cloud_assembly = mock_cloud_assembly(file_assets)
    mock_bucket(mocker)
    mock_dict = mock_bucket_object_utils(mocker)
    bucket = dummy_cluster_bucket()

    cdk_assets_manager = CDKAssetsManager(cluster_cloud_assembly)
    cdk_assets_manager.upload_assets(bucket)

    bucket_upload_asset_mock = mock_dict.get("upload_cfn_asset")
    bucket_upload_asset_mock.assert_called_with(asset_file_content=asset_content, asset_name=file_assets[0].id)
