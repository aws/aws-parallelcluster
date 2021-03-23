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
import os
import re
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

import yaml


def download_file(url):
    """Download file from given url."""
    response = urlopen(url)  # nosec
    return response.read().decode("utf-8")


def load_yaml_dict(file_path):
    """Read the content of a yaml file."""
    with open(file_path) as conf_file:
        yaml_content = yaml.load(conf_file, Loader=yaml.SafeLoader)
    # TODO prevent yaml.load from converting 1:00:00 to int 3600

    # TODO use from cfn_flip import load_yaml
    return yaml_content


def load_yaml(source_dir, file_name):
    """Get string data from yaml file."""
    return yaml.dump(load_yaml_dict(os.path.join(source_dir, file_name)))


def validate_json_format(data):
    """Validate the input data in json format."""
    try:
        json.loads(data)
    except ValueError:
        return False
    return True


def get_url_scheme(url):
    """Parse url to get scheme."""
    return urlparse(url).scheme


def parse_bucket_url(url):
    """
    Parse s3 url to get bucket name and object name.

    input: s3://test/templates/3.0/post_install.sh
    output: {"bucket_name": "test", "object_key": "templates/3.0/post_install.sh", "object_name": "post_install.sh"}
    """
    match = re.match(r"s3://(.*?)/(.*)", url)
    if match:
        bucket_name = match.group(1)
        object_key = match.group(2)
        object_name = object_key.split("/")[-1]
    else:
        raise URLError("Invalid s3 url: {0}".format(url))

    return {"bucket_name": bucket_name, "object_key": object_key, "object_name": object_name}
