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

import pytest
from assertpy import assert_that
from tests.pcluster.models.imagebuilder_dummy_model import imagebuilder_factory

from pcluster.models.imagebuilder_extra_attributes import ChefAttributes


@pytest.mark.parametrize(
    "resource, dna_json",
    [
        (
            {
                "dev_settings": {
                    "cookbook": {
                        "chef_cookbook": "file:///test/aws-parallelcluster-cookbook-3.0.tgz",
                        "extra_chef_attributes": '{"nvidia": { "enabled" : "true" }, "dcv" :"false"}',
                    },
                    "node_package": "s3://test/aws-parallelcluster-node-3.0.tgz",
                },
            },
            {
                "cfncluster": {
                    "cfn_region": "{{ build.AWSRegion.outputs.stdout }}",
                    "nvidia": {"enabled": "true"},
                    "is_official_ami_build": "false",
                    "custom_node_package": "s3://test/aws-parallelcluster-node-3.0.tgz",
                    "custom_awsbatchcli_package": "",
                    "cfn_base_os": "{{ build.OperatingSystemName.outputs.stdout }}",
                    "dcv": "false",
                }
            },
        ),
        (
            {
                "dev_settings": {
                    "cookbook": {
                        "chef_cookbook": "file:///test/aws-parallelcluster-cookbook-3.0.tgz",
                        "extra_chef_attributes": '{"nvidia": { "enabled" : "true" }, "dcv" :"false", '
                        '"cluster":{"cfn_slots":"cores"}}',
                    },
                    "aws_batch_cli_package": "https://test/aws-parallelcluster-3.0.tgz",
                },
            },
            {
                "cfncluster": {
                    "cfn_region": "{{ build.AWSRegion.outputs.stdout }}",
                    "nvidia": {"enabled": "true"},
                    "is_official_ami_build": "false",
                    "custom_node_package": "",
                    "custom_awsbatchcli_package": "https://test/aws-parallelcluster-3.0.tgz",
                    "cfn_base_os": "{{ build.OperatingSystemName.outputs.stdout }}",
                    "dcv": "false",
                    "cluster": {"cfn_slots": "cores"},
                }
            },
        ),
    ],
)
def test_chef_attributes(resource, dna_json):
    dev_settings = imagebuilder_factory(resource).get("dev_settings")
    chef_attributes = ChefAttributes(dev_settings).dump_json()
    assert_that(chef_attributes).is_equal_to(json.dumps(dna_json))
