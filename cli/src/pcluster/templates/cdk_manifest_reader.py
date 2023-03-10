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
import jmespath

from pcluster.utils import LOGGER


class CDKManifestReader:
    """
    Reads the manifest file in a cloud assembly directory.

    It also has convenience methods to get the manifest info in a structured way.
    """

    def __init__(self, manifest_json: str):
        self._manifest_json = manifest_json

    def get_assets(self, stack_name):
        """
        Return a mapping of the asset's id and the associated asset data.

        Output:
        ```
        [
            {
                "path": "<Path on disk to the asset>",
                "id": "<Logical identifier for the asset>",
                "packaging": "<Type of asset>",
                "sourceHash": "<The hash of the asset source>",
                "s3BucketParameter": "<Name of parameter where S3 bucket should be passed in>",
                "s3KeyParameter": "<Name of parameter where S3 key should be passed in>",
                "artifactHashParameter": "<The name of the parameter where the hash of the bundled
                 asset should be passed in>"
            },
            ...
        ]
        ```
        For more info, see:
        https://github.com/aws/aws-cdk/blob/v1-main/packages/%40aws-cdk/cloud-assembly-schema/schema/cloud-assembly.schema.json
        """
        cdk_assets = (
            jmespath.search(
                f'artifacts."{stack_name}".metadata."/{stack_name}"[?type==`aws:cdk:asset`].data', self._manifest_json
            )
            or []
        )
        LOGGER.info(f"CDK assets in cloud assembly directory: {cdk_assets}")
        return cdk_assets
