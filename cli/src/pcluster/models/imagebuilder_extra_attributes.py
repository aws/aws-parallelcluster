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
import json

from pcluster.models.imagebuilder import ImagebuilderDevSettings


class ChefAttributes:
    """Attributes for Chef Client."""

    def __init__(self, dev_settings: ImagebuilderDevSettings):
        self.cfn_region = None
        self.nvidia = None
        self.is_official_ami_build = None
        self.custom_node_package = None
        self.cfn_base_os = None
        self._extra_attributes_json = {}
        self._set_default(dev_settings)
        self._set_extra_attributes(dev_settings)

    def _set_default(self, dev_settings: ImagebuilderDevSettings):
        self.cfn_region = "{{ build.AWSRegion.outputs.stdout }}"
        self.nvidia = {"enabled": "false"}
        self.is_official_ami_build = (
            str.lower(str(dev_settings.update_os_and_reboot))
            if dev_settings and dev_settings.update_os_and_reboot
            else "false"
        )
        self.custom_node_package = dev_settings.node_package if dev_settings and dev_settings.node_package else ""
        self.cfn_base_os = "{{ build.OperatingSystemName.outputs.stdout }}"

    def _set_extra_attributes(self, dev_settings: ImagebuilderDevSettings):
        if dev_settings and dev_settings.cookbook and dev_settings.cookbook.extra_chef_attributes:
            extra_attributes = json.loads(dev_settings.cookbook.extra_chef_attributes)
            for key, value in extra_attributes.items():
                if key in self.__dict__:
                    self.__dict__.update({key: value})
                else:
                    self._extra_attributes_json.update({key: value})

    def dump_json(self):
        """Dump chef attribute json to string."""
        default_attributes_json = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        default_attributes_json.update(self._extra_attributes_json)
        attribute_json = {"cfncluster": default_attributes_json}
        return json.dumps(attribute_json)
