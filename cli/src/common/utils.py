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

from urllib.request import urlopen

import yaml


def download_file(url):
    """Download file from given url"""
    response = urlopen(url)
    return response.read().decode("utf-8")


def load_yaml(config_file):
    """Read the content of a yaml file."""
    with open(config_file) as conf_file:
        yaml_content = yaml.load(conf_file, Loader=yaml.SafeLoader)

    # TODO use from cfn_flip import load_yaml
    return yaml_content
