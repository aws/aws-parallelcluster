# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import pytest

from assertpy import assert_that
from pcluster.config.pcluster_config import PclusterConfig


def test_update_sections(mocker, pcluster_config_reader):
    mocker.patch("pcluster.config.param_types.get_supported_architectures_for_instance_type", return_value=["x86_64"])
    pcluster_config = PclusterConfig(
        cluster_label="default", config_file=pcluster_config_reader(), fail_on_file_absence=True, fail_on_error=True,
    )

    ebs1 = pcluster_config.get_section("ebs", "ebs1")
    assert_that(ebs1).is_not_none()
    assert_that(ebs1.get_param_value("shared_dir")).is_equal_to("ebs1")
    assert_that(pcluster_config.get_section("cluster").get_param_value("ebs_settings")).is_equal_to("ebs1,ebs2")

    # Test section re-labelling:
    # Update a section label and verify that pcluster_config_get_section() works correctly
    ebs1.label = "ebs1_updated"

    assert_that(pcluster_config.get_section("ebs", "ebs1")).is_none()
    ebs1_updated = pcluster_config.get_section("ebs", "ebs1_updated")
    assert_that(ebs1_updated).is_not_none()
    assert_that(ebs1_updated.get_param_value("shared_dir")).is_equal_to("ebs1")
    assert_that(pcluster_config.get_section("cluster").get_param_value("ebs_settings")).is_equal_to("ebs1_updated,ebs2")

    # Test removing section
    # Remove a section and verify that ebs_settings param is updated accordingly
    ebs2 = pcluster_config.get_section("ebs", "ebs2")
    pcluster_config.remove_section(ebs2.key, ebs2.label)
    assert_that(pcluster_config.get_section("cluster").get_param_value("ebs_settings")).is_equal_to("ebs1_updated")

    # Test adding section
    # Add a section and verify that ebs_settings param is updated accordingly
    pcluster_config.add_section(ebs2)
    assert_that(pcluster_config.get_section("cluster").get_param_value("ebs_settings")).is_equal_to("ebs1_updated,ebs2")

    # Test removing multiple sections by key
    # Removing sections by key should be prevented if there are multiple sections with the same key
    with pytest.raises(Exception):
        pcluster_config.remove_section("ebs")
