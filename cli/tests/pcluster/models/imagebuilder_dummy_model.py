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
from pcluster.models.common import BaseTag, Cookbook, S3Bucket
from pcluster.models.imagebuilder_config import (
    Build,
    Component,
    DistributionConfiguration,
    Image,
    ImageBuilderConfig,
    ImagebuilderDevSettings,
    Volume,
)

CLASS_DICT = {
    "imagebuilder": ImageBuilderConfig,
    "image": Image,
    "build": Build,
    "dev_settings": ImagebuilderDevSettings,
    "root_volume": Volume,
    "tags": BaseTag,
    "components": Component,
    "cookbook": Cookbook,
    "distribution_configuration": DistributionConfiguration,
}


def imagebuilder_factory(resource):
    """Generate an imagebuilder related resource object by resource dict."""
    object_dict = {}
    for r in resource.keys():
        value = resource.get(r)
        if isinstance(value, list):
            temp = []
            if r in CLASS_DICT:
                cls = CLASS_DICT.get(r)
                for kwargs in value:
                    temp.append(cls(**kwargs))
            else:
                temp = value
            object_dict[r] = temp
        elif r in CLASS_DICT:
            kwargs = imagebuilder_factory(value)
            cls = CLASS_DICT.get(r)
            object_dict[r] = cls(**kwargs)
        else:
            object_dict[r] = value
    return object_dict


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
