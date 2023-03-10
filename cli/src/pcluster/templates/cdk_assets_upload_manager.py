# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
#
# This module contains all the classes representing the Resources objects.
# These objects are obtained from the configuration file through a conversion based on the Schema classes.
#
import os
import typing

from pcluster.models.s3_bucket import S3Bucket, S3FileType
from pcluster.templates.cdk_manifest_reader import CDKManifestReader
from pcluster.utils import LOGGER, load_yaml_dict


class CDKAssetsUploadManager:
    """Manage the upload  of CDK Assets to the cluster S3 bucket."""

    def __init__(self, cloud_assembly_dir: typing.Union[str, os.PathLike], cdk_manifest_reader: CDKManifestReader):
        self._assets_metadata = {}
        self._cloud_assembly_dir = cloud_assembly_dir
        self._cdk_manifest_reader = cdk_manifest_reader

    def upload_assets(self, stack_name: str, bucket: S3Bucket):
        """
        Upload the assets in the cloud assembly directory to the cluster artifacts S3 Bucket.

        Returns a mapping of the Asset Logical ID and associated parameters to be passed to the root template.
        Output:
        ```
        [
            {
                'hash_parameter': {
                    'key': 'AssetParameters<ASSET_LOGICAL_ID>ArtifactHash<ALPHANUMERIC>', 'value': ''
                },
                's3_bucket_parameter': {
                    'key': 'AssetParameters<ASSET_LOGICAL_ID>S3Bucket<ALPHANUMERIC>', 'value': '<CLUSTER_S3_BUCKET>'
                },
                's3_object_key_parameter': {
                    'key': 'AssetParameters<ASSET_LOGICAL_ID>S3VersionKey<ALPHANUMERIC>', 'value': '<ASSET_OBJECT_KEY>'
                }
            },
            ...
        ]
        ```
        """
        cdk_assets = self._cdk_manifest_reader.get_assets(stack_name=stack_name)
        self._assets_metadata = []

        for cdk_asset in cdk_assets:
            asset_file_path = os.path.join(self._cloud_assembly_dir, cdk_asset["path"])
            asset_file_content = load_yaml_dict(asset_file_path)
            asset_id = cdk_asset["id"]
            self._assets_metadata.append(
                {
                    # `artifactHashParameter` only needed when using `cdk deploy` to check the integrity of files
                    # uploaded to S3
                    "hash_parameter": {"key": cdk_asset["artifactHashParameter"], "value": ""},
                    "s3_bucket_parameter": {"key": cdk_asset["s3BucketParameter"], "value": bucket.name},
                    "s3_object_key_parameter": {
                        "key": cdk_asset["s3KeyParameter"],
                        "value": bucket.get_object_key(S3FileType.ASSETS, asset_id),
                    },
                    "content": asset_file_content,
                }
            )
            LOGGER.info(f"Uploading asset {asset_id} to S3")
            bucket.upload_cfn_asset(asset_file_content=asset_file_content, asset_name=asset_id)

        return self._assets_metadata
