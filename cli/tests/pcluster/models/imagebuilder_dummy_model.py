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
from pcluster.models.common import BaseTag, Cookbook
from pcluster.models.imagebuilder import Build, Component, Image, ImageBuilder, ImagebuilderDevSettings, Volume

CLASS_DICT = {
    "imagebuilder": ImageBuilder,
    "image": Image,
    "build": Build,
    "dev_settings": ImagebuilderDevSettings,
    "root_volume": Volume,
    "tag": BaseTag,
    "component": Component,
    "cookbook": Cookbook,
}


def dummy_imagebuilder(is_official_ami_build):
    """Generate dummy imagebuilder configuration."""
    image = Image(name="Pcluster")
    if is_official_ami_build:
        build = Build(
            instance_type="c5.xlarge", parent_image="arn:aws:imagebuilder:us-east-1:aws:image/amazon-linux-2-x86/x.x.x"
        )
        dev_settings = ImagebuilderDevSettings(update_os_and_reboot=True)
    else:
        build = Build(instance_type="g4dn.xlarge", parent_image="ami-0185634c5a8a37250")
        dev_settings = ImagebuilderDevSettings()
    return ImageBuilder(image=image, build=build, dev_settings=dev_settings)


def imagebuilder_factory(resource):
    """Generate an imagebuilder related resource object by resource dict."""
    object_dict = {}
    for r in resource.keys():
        value = resource.get(r)
        if isinstance(value, list):
            temp = []
            for v in value:
                if isinstance(v, dict):
                    for dict_key, dict_value in v.items():
                        kwargs = imagebuilder_factory(dict_value)
                        cls = CLASS_DICT.get(dict_key)
                        temp.append(cls(**kwargs))
                else:
                    temp.extend(v)
            object_dict[r] = temp
        if r in CLASS_DICT:
            kwargs = imagebuilder_factory(value)
            cls = CLASS_DICT.get(r)
            object_dict[r] = cls(**kwargs)
        else:
            object_dict[r] = value
    return object_dict
