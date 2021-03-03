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

from api.pcluster_api import PclusterApi
from common.utils import load_yaml_dict


def test_pcluster_api_build_image(test_datadir):
    # A draft test to verify stack creation
    input_yaml = load_yaml_dict(test_datadir / "imagebuilder_config_required.yaml")

    response = PclusterApi.build_image(
        imagebuilder_config=input_yaml, image_name="test10", region="us-east-1", disable_rollback=False
    )

    print(response.__repr__())
