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
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

from aws_cdk.cx_api import CloudFormationStackArtifact

from pcluster.models.s3_bucket import S3Bucket, S3FileType
from pcluster.utils import LOGGER, load_yaml_dict


@dataclass
class ClusterAssetFile:
    """Class for asset files generated from a CDK Synthesis."""

    id: str
    path: str
    artifact_hash_parameter: str
    s3_bucket_parameter: str
    s3_key_parameter: str


class ClusterCloudAssembly(ABC):
    """Wrapper for cloud assembly of a cluster after running `app.synth()`."""

    def __init__(self, cloud_assembly):
        self.cloud_assembly = cloud_assembly

    @abstractmethod
    def get_assets(self) -> List[ClusterAssetFile]:
        """List of asset files info."""
        pass

    @abstractmethod
    def get_cloud_assembly_directory(self) -> str:
        """Directory of the cloud assembly files."""
        pass


class CDKV1ClusterCloudAssembly(ClusterCloudAssembly):
    """Implementation of with CDK V1 Cloud Assembly properties."""

    def get_assets(self) -> List[ClusterAssetFile]:
        """List of asset files info."""
        cfn_stack_artifact = next(
            artifact for artifact in self.cloud_assembly.artifacts if isinstance(artifact, self._get_artifacts_class())
        )
        assets = cfn_stack_artifact.assets
        cluster_assets_files = [
            ClusterAssetFile(
                id=asset.id,
                path=asset.path,
                s3_bucket_parameter=asset.s3_bucket_parameter,
                s3_key_parameter=asset.s3_key_parameter,
                artifact_hash_parameter=asset.artifact_hash_parameter,
            )
            for asset in assets
        ]
        return cluster_assets_files

    def get_cloud_assembly_directory(self) -> str:
        """Directory of the cloud assembly files."""
        return self.cloud_assembly.directory

    @staticmethod
    def _get_artifacts_class():
        return CloudFormationStackArtifact


class CDKAssetsManager:
    """Manage the discovery and upload of CDK Assets to the cluster S3 bucket."""

    def __init__(self, cluster_cloud_assembly: ClusterCloudAssembly):
        self._assets_metadata = {}
        self.cluster_cdk_assembly = cluster_cloud_assembly

    def upload_assets(self, bucket: S3Bucket):
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
        cdk_assets = self.cluster_cdk_assembly.get_assets()
        self._assets_metadata = []

        for cdk_asset in cdk_assets:
            asset_file_path = os.path.join(self.cluster_cdk_assembly.get_cloud_assembly_directory(), cdk_asset.path)
            asset_file_content = load_yaml_dict(asset_file_path)
            asset_id = cdk_asset.id
            self._assets_metadata.append(
                {
                    # `artifactHashParameter` only needed when using `cdk deploy` to check the integrity of files
                    # uploaded to S3
                    "hash_parameter": {"key": cdk_asset.artifact_hash_parameter, "value": ""},
                    "s3_bucket_parameter": {"key": cdk_asset.s3_bucket_parameter, "value": bucket.name},
                    "s3_object_key_parameter": {
                        "key": cdk_asset.s3_key_parameter,
                        "value": bucket.get_object_key(S3FileType.ASSETS, asset_id),
                    },
                    "content": asset_file_content,
                }
            )
            LOGGER.info(f"Uploading asset {asset_id} to S3")
            bucket.upload_cfn_asset(asset_file_content=asset_file_content, asset_name=asset_id)

        return self._assets_metadata
