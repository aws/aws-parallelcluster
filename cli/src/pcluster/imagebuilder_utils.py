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
import os

import yaml

from pcluster.aws.aws_api import AWSApi
from pcluster.utils import get_url_scheme, yaml_load

ROOT_VOLUME_TYPE = "gp3"
PCLUSTER_RESERVED_VOLUME_SIZE = 27
AMI_NAME_REQUIRED_SUBSTRING = " {{ imagebuilder:buildDate }}"


def get_ami_id(parent_image):
    """Get ami id from parent image, parent image could be image id or image arn."""
    if parent_image and parent_image.startswith("arn"):
        ami_id = AWSApi.instance().imagebuilder.get_image_id(parent_image)
    else:
        ami_id = parent_image
    return ami_id


def get_resources_directory():
    """Get imagebuilder resources directory."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(current_dir, "..", "pcluster", "resources")


def search_tag(resource_info, tag_key):
    """Search tag in tag list by given tag key."""
    return next(
        (tag["Value"] for tag in resource_info.get("Tags", []) if tag["Key"] == tag_key),
        None,
    )


def wrap_script_to_component(url):
    """Wrap script to custom component data property."""
    scheme = get_url_scheme(url)
    current_dir = os.path.dirname(os.path.abspath(__file__))

    custom_component_script_template_file = os.path.join(current_dir, "resources", "imagebuilder", "custom_script.yaml")

    with open(custom_component_script_template_file, "r", encoding="utf-8") as file:
        custom_component_script_template = yaml_load(file)

    script_url_action = _generate_action("ScriptUrl", "set -v\necho {0}\n".format(url))
    custom_component_script_template["phases"][0]["steps"].insert(0, script_url_action)
    script_scheme_action = _generate_action("ScriptUrlScheme", "set -v\necho {0}\n".format(scheme))
    custom_component_script_template["phases"][0]["steps"].insert(0, script_scheme_action)

    return yaml.dump(custom_component_script_template)


def _generate_action(action_name, commands):
    """Generate action in imagebuilder components."""
    action = {"name": action_name, "action": "ExecuteBash", "inputs": {"commands": [commands]}}
    return action
