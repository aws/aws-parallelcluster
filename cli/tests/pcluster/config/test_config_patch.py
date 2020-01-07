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
import os
import shutil

import pytest

from pcluster.config.config_patch import Change, ConfigPatch
from pcluster.config.param_types import Updatability as Upd
from pcluster.config.pcluster_config import PclusterConfig

defaults = {
    "master_subnet_id": "subnet-12345678",
    "compute_subnet_id": "subnet-12345678",
    "additional_sg": "sg-12345678",
}


def check_patch(src_conf, dst_conf, expected_changes, expected_patch_updatability):
    patch = ConfigPatch(base_config=src_conf, target_config=dst_conf)
    assert set(patch.changes) == set(expected_changes)
    assert patch.updatability == expected_patch_updatability


def test_config_patch(mocker):
    mocker.patch("pcluster.config.param_types.get_avail_zone", return_value="mocked_avail_zone")
    src_conf = PclusterConfig()
    dst_conf = PclusterConfig()
    # Two new configs must always be equal
    check_patch(src_conf, dst_conf, [], Upd.ALLOWED)


def duplicate_config_file(dst_config_file, test_datadir):
    # Make a copy of the src template to the target file.
    # The two resulting PClusterConfig instances will be identical
    src_config_file_path = os.path.join(str(test_datadir), "pcluster.config.ini")
    dst_config_file_path = os.path.join(str(test_datadir), dst_config_file)
    shutil.copy(src_config_file_path, dst_config_file_path)


@pytest.mark.parametrize(
    "section_key, section_label, param_key, src_param_value, dst_param_value, change_applicability, "
    "patch_applicability",
    [
        ("vpc", "default", "master_subnet_id", "subnet-12345678", "subnet-1234567a", Upd.DENIED, Upd.DENIED),
        ("vpc", "default", "additional_sg", "sg-12345678", "sg-1234567a", Upd.ALLOWED, Upd.ALLOWED),
        ("vpc", "default", "additional_sg", "sg-12345678", "sg-1234567a", Upd.ALLOWED, Upd.ALLOWED),
    ],
)
def test_single_param_change(
    test_datadir,
    pcluster_config_reader,
    mocker,
    section_key,
    section_label,
    param_key,
    src_param_value,
    dst_param_value,
    change_applicability,
    patch_applicability,
):
    mocker.patch("pcluster.config.param_types.get_avail_zone", return_value="mocked_avail_zone")
    dst_config_file = "pcluster.config.dst.ini"
    duplicate_config_file(dst_config_file, test_datadir)

    src_dict = {}
    src_dict.update(defaults)
    src_dict[param_key] = src_param_value

    rendered_config_file = pcluster_config_reader(**src_dict)
    src_conf = PclusterConfig(config_file=rendered_config_file, fail_on_file_absence=True)

    dst_dict = {}
    dst_dict.update(defaults)
    dst_dict[param_key] = dst_param_value
    rendered_config_file = pcluster_config_reader(dst_config_file, **dst_dict)
    dst_conf = PclusterConfig(config_file=rendered_config_file,)

    change = Change(section_key, section_label, param_key, src_param_value, dst_param_value, change_applicability)
    check_patch(src_conf, dst_conf, [change], patch_applicability)


def test_multiple_param_changes(mocker, pcluster_config_reader, test_datadir):
    mocker.patch("pcluster.config.param_types.get_avail_zone", return_value="mocked_avail_zone")
    dst_config_file = "pcluster.config.dst.ini"
    duplicate_config_file(dst_config_file, test_datadir)

    src_dict = {}
    src_dict.update(defaults)
    src_dict["master_subnet_id"] = "subnet-12345678"
    src_dict["compute_subnet_id"] = "subnet-12345678"
    src_dict["additional_sg"] = "sg-12345678"

    rendered_config_file = pcluster_config_reader(**src_dict)
    src_conf = PclusterConfig(config_file=rendered_config_file, fail_on_file_absence=True)

    dst_dict = {}
    dst_dict.update(defaults)
    dst_dict["master_subnet_id"] = "subnet-1234567a"
    dst_dict["compute_subnet_id"] = "subnet-1234567a"
    dst_dict["additional_sg"] = "sg-1234567a"

    rendered_config_file = pcluster_config_reader(dst_config_file, **dst_dict)
    dst_conf = PclusterConfig(config_file=rendered_config_file,)

    check_patch(
        src_conf,
        dst_conf,
        [
            Change("vpc", "default", "master_subnet_id", "subnet-12345678", "subnet-1234567a", Upd.DENIED),
            Change("vpc", "default", "compute_subnet_id", "subnet-12345678", "subnet-1234567a", Upd.DENIED),
            Change("vpc", "default", "additional_sg", "sg-12345678", "sg-1234567a", Upd.ALLOWED),
        ],
        Upd.DENIED,
    )


def _test_equal_configs(base_conf, target_conf):
    # Without doing any changes the two configs must be equal
    check_patch(base_conf, target_conf, [], Upd.ALLOWED)


def _test_less_target_sections(base_conf, target_conf):
    # Remove an ebs section in the target conf
    assert target_conf.get_section("ebs", "ebs-1") is not None
    target_conf.remove_section("ebs", "ebs-1")
    assert target_conf.get_section("ebs", "ebs-1") is None

    patch = None
    # A patch cannot be created because of the different number of sections
    with pytest.raises(Exception):
        patch = ConfigPatch(base_config=base_conf, target_config=target_conf)
    assert not patch


def _test_more_target_sections(base_conf, target_conf):
    # Remove an ebs section into the base conf
    assert base_conf.get_section("ebs", "ebs-1") is not None
    base_conf.remove_section("ebs", "ebs-1")
    assert base_conf.get_section("ebs", "ebs-1") is None

    patch = None
    # A patch cannot be created because of the different number of sections
    with pytest.raises(Exception):
        patch = ConfigPatch(base_config=base_conf, target_config=target_conf)
    assert not patch


def _test_incompatible_ebs_sections(base_conf, target_conf):
    # Change shared_dir param value in target conf
    target_conf.get_section("ebs", "ebs-1").get_param("shared_dir").value = "new_value"
    # A patch cannot be created because of the different number of sections
    with pytest.raises(Exception):
        ConfigPatch(base_config=base_conf, target_config=target_conf)


def _test_different_labels_only(base_conf, target_conf):
    # First make sure sections are present with original labels

    base_ebs_1_section = base_conf.get_section("ebs", "ebs-1")
    base_ebs_2_section = base_conf.get_section("ebs", "ebs-2")

    assert base_conf.get_section("ebs", "ebs-1")
    assert base_conf.get_section("ebs", "ebs-2")

    # Now update section labels and make sure they're not more present with original labels
    base_ebs_1_section.label = "ebs-1_updated"
    base_ebs_2_section.label = "ebs-2_updated"

    assert base_conf.get_section("ebs", "ebs-1_updated")
    assert base_conf.get_section("ebs", "ebs-2_updated")
    assert not base_conf.get_section("ebs", "ebs-1")
    assert not base_conf.get_section("ebs", "ebs-2")

    # Now create the patch
    patch = ConfigPatch(base_conf, target_conf)

    # The patch should not contain any difference
    assert patch.changes == []

    # The section labels in the target config must have been restored
    assert not base_conf.get_section("ebs", "ebs-1_updated")
    assert not base_conf.get_section("ebs", "ebs-2_updated")
    assert base_conf.get_section("ebs", "ebs-1")
    assert base_conf.get_section("ebs", "ebs-2")


@pytest.mark.parametrize(
    "test",
    [
        _test_less_target_sections,
        _test_more_target_sections,
        _test_incompatible_ebs_sections,
        _test_equal_configs,
        _test_different_labels_only,
    ],
)
def test_adaptation(mocker, test_datadir, pcluster_config_reader, test):
    mocker.patch("pcluster.config.param_types.get_avail_zone", return_value="mocked_avail_zone")
    base_config_file = "pcluster.config.base.ini"
    duplicate_config_file(base_config_file, test_datadir)
    target_config_file = "pcluster.config.dst.ini"
    duplicate_config_file(target_config_file, test_datadir)

    rendered_base_config_file = pcluster_config_reader(base_config_file, **defaults)
    rendered_target_config_file = pcluster_config_reader(target_config_file, **defaults)

    base_conf = PclusterConfig(config_file=rendered_base_config_file, fail_on_file_absence=True)
    target_conf = PclusterConfig(config_file=rendered_target_config_file, fail_on_file_absence=True)

    test(base_conf, target_conf)
