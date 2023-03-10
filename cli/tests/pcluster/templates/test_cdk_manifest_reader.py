#  Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import pytest
from assertpy import assert_that

from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.templates.cdk_manifest_reader import CDKManifestReader


@pytest.mark.parametrize(
    "manifest_file_name, expected_assets_info",
    [
        (
            "manifest.json",
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
        )
    ],
)
def test_cdk_manifest_reader(datadir, manifest_file_name, expected_assets_info):
    cdk_manifest_reader = CDKManifestReader(CDKTemplateBuilder.load_manifest_json(datadir))
    assets = cdk_manifest_reader.get_assets("TestStack")
    assert_that(assets).is_equal_to(expected_assets_info)
