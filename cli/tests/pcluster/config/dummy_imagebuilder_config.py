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
from pcluster.config.common import BaseTag, Cookbook, Imds, LambdaFunctionsVpcConfig
from pcluster.config.imagebuilder_config import (
    AdditionalIamPolicy,
    Build,
    Component,
    DistributionConfiguration,
    Iam,
    Image,
    ImageBuilderConfig,
    ImagebuilderDeploymentSettings,
    ImagebuilderDevSettings,
    Installation,
    LustreClient,
    NvidiaSoftware,
    UpdateOsPackages,
    Volume,
)

CLASS_DICT = {
    "imagebuilder": ImageBuilderConfig,
    "image": Image,
    "build": Build,
    "dev_settings": ImagebuilderDevSettings,
    "lambda_functions_vpc_config": LambdaFunctionsVpcConfig,
    "deployment_settings": ImagebuilderDeploymentSettings,
    "root_volume": Volume,
    "tags": BaseTag,
    "components": Component,
    "cookbook": Cookbook,
    "distribution_configuration": DistributionConfiguration,
    "iam": Iam,
    "additional_iam_policies": AdditionalIamPolicy,
    "update_os_packages": UpdateOsPackages,
    "imds": Imds,
    "installation": Installation,
    "lustre_client": LustreClient,
    "nvidia_software": NvidiaSoftware,
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
