#  Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import tempfile

import pytest

from pcluster.templates.cdk_assets_upload_manager import CDKAssetsUploadManager
from pcluster.templates.cdk_manifest_reader import CDKManifestReader
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket, mock_bucket_object_utils


@pytest.mark.parametrize(
    "assets_metadata, asset_content",
    [
        (
            [
                {
                    "path": "asset_path",
                    "id": "asset_logical_id",
                    "packaging": "file",
                    "sourceHash": "asset_hash",
                    "s3BucketParameter": "asset_s3_bucket",
                    "s3KeyParameter": "asset_s3_key",
                    "artifactHashParameter": "asset_hash_parameter",
                }
            ],
            "asset_content",
        )
    ],
)
def test_upload_assets(mocker, assets_metadata, asset_content):
    mocker.patch(
        "pcluster.templates.cdk_manifest_reader.CDKManifestReader.get_assets",
        return_value=assets_metadata,
    )
    mocker.patch("pcluster.templates.cdk_assets_upload_manager.load_yaml_dict", return_value=asset_content)
    mock_bucket(mocker)
    mock_dict = mock_bucket_object_utils(mocker)
    bucket = dummy_cluster_bucket()

    with tempfile.TemporaryDirectory() as tempdir:
        cdk_manifest_reader = CDKManifestReader(tempdir)
        cdk_assets_upload_manager = CDKAssetsUploadManager(tempdir, cdk_manifest_reader)
        cdk_assets_upload_manager.upload_assets("TestStack", bucket)

    bucket_upload_asset_mock = mock_dict.get("upload_cfn_asset")
    bucket_upload_asset_mock.assert_called_with(asset_file_content=asset_content, asset_name=assets_metadata[0]["id"])
