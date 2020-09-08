# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from pcluster.config.config_patch import Change, ConfigPatch
from pcluster.config.pcluster_config import PclusterConfig
from pcluster.config.update_policy import UpdatePolicy
from tests.pcluster.config.utils import duplicate_config_file

default_cluster_params = {
    "master_subnet_id": "subnet-12345678",
    "compute_subnet_id": "subnet-12345678",
    "additional_sg": "sg-12345678",
    "initial_queue_size": 0,
    "max_queue_size": 10,
    "maintain_initial_size": False,
    "compute_instance_type": "t2.micro",
}


def _do_mocking_for_tests(mocker):
    """Perform the mocking common to all of these test cases."""
    mocker.patch("pcluster.config.cfn_param_types.get_availability_zone_of_subnet", return_value="mocked_avail_zone")
    mocker.patch(
        "pcluster.config.cfn_param_types.get_supported_architectures_for_instance_type", return_value=["x86_64"]
    )


def _check_patch(src_conf, dst_conf, expected_changes, expected_patch_policy):
    patch = ConfigPatch(base_config=src_conf, target_config=dst_conf)
    ignored_params = ["cluster_config_metadata"]

    changes = [change for change in patch.changes if change.param_key not in ignored_params]
    assert_that(sorted(changes)).is_equal_to(sorted(expected_changes))
    assert_that(patch.update_policy_level).is_equal_to(expected_patch_policy.level)


def test_config_patch(mocker):
    _do_mocking_for_tests(mocker)
    src_conf = PclusterConfig()
    dst_conf = PclusterConfig()
    # Two new configs must always be equal
    _check_patch(src_conf, dst_conf, [], UpdatePolicy.SUPPORTED)


@pytest.mark.parametrize(
    "section_key, section_label, param_key, src_param_value, dst_param_value, change_update_policy",
    [
        ("vpc", "default", "master_subnet_id", "subnet-12345678", "subnet-1234567a", UpdatePolicy.UNSUPPORTED),
        ("vpc", "default", "additional_sg", "sg-12345678", "sg-1234567a", UpdatePolicy.SUPPORTED),
        ("cluster", "default", "initial_queue_size", 0, 1, UpdatePolicy.SUPPORTED),
        ("cluster", "default", "max_queue_size", 0, 1, UpdatePolicy.SUPPORTED),
        ("cluster", "default", "maintain_initial_size", 0, 1, UpdatePolicy.SUPPORTED),
        ("cluster", "default", "compute_instance_type", "t2.micro", "c4.xlarge", UpdatePolicy.COMPUTE_FLEET_STOP),
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
    change_update_policy,
):
    _do_mocking_for_tests(mocker)
    dst_config_file = "pcluster.config.dst.ini"
    duplicate_config_file(dst_config_file, test_datadir)

    src_dict = {}
    src_dict.update(default_cluster_params)
    src_dict[param_key] = src_param_value

    src_config_file = pcluster_config_reader(**src_dict)
    src_conf = PclusterConfig(config_file=src_config_file, fail_on_file_absence=True)

    dst_dict = {}
    dst_dict.update(default_cluster_params)
    dst_dict[param_key] = dst_param_value
    dst_config_file = pcluster_config_reader(dst_config_file, **dst_dict)
    dst_conf = PclusterConfig(config_file=dst_config_file)

    expected_change = Change(
        section_key, section_label, param_key, src_param_value, dst_param_value, change_update_policy
    )
    _check_patch(src_conf, dst_conf, [expected_change], change_update_policy)


def test_multiple_param_changes(mocker, pcluster_config_reader, test_datadir):
    _do_mocking_for_tests(mocker)
    dst_config_file = "pcluster.config.dst.ini"
    duplicate_config_file(dst_config_file, test_datadir)

    src_dict = {}
    src_dict.update(default_cluster_params)
    src_dict["master_subnet_id"] = "subnet-12345678"
    src_dict["compute_subnet_id"] = "subnet-12345678"
    src_dict["additional_sg"] = "sg-12345678"

    src_config_file = pcluster_config_reader(**src_dict)
    src_conf = PclusterConfig(config_file=src_config_file, fail_on_file_absence=True)

    dst_dict = {}
    dst_dict.update(default_cluster_params)
    dst_dict["master_subnet_id"] = "subnet-1234567a"
    dst_dict["compute_subnet_id"] = "subnet-1234567a"
    dst_dict["additional_sg"] = "sg-1234567a"

    dst_config_file = pcluster_config_reader(dst_config_file, **dst_dict)
    dst_conf = PclusterConfig(config_file=dst_config_file)

    expected_changes = [
        Change("vpc", "default", "master_subnet_id", "subnet-12345678", "subnet-1234567a", UpdatePolicy.UNSUPPORTED),
        Change(
            "vpc", "default", "compute_subnet_id", "subnet-12345678", "subnet-1234567a", UpdatePolicy.COMPUTE_FLEET_STOP
        ),
        Change("vpc", "default", "additional_sg", "sg-12345678", "sg-1234567a", UpdatePolicy.SUPPORTED),
    ]

    _check_patch(src_conf, dst_conf, expected_changes, UpdatePolicy.UNSUPPORTED)


def _test_equal_configs(base_conf, target_conf):
    # Without doing any changes the two configs must be equal
    _check_patch(base_conf, target_conf, [], UpdatePolicy.SUPPORTED)


def _test_less_target_sections(base_conf, target_conf):
    # Remove an ebs section in the target conf
    assert_that(target_conf.get_section("ebs", "ebs-1")).is_not_none()
    target_conf.remove_section("ebs", "ebs-1")
    assert_that(target_conf.get_section("ebs", "ebs-1")).is_none()

    # The patch must show 2 differences: one for ebs_settings and one for missing ebs section in target conf
    _check_patch(
        base_conf,
        target_conf,
        [
            Change(
                "cluster",
                "default",
                "ebs_settings",
                "ebs-1,ebs-2",
                "ebs-2",
                UpdatePolicy(
                    UpdatePolicy.UNSUPPORTED,
                    fail_reason="EBS sections cannot be added or removed during a 'pcluster update' operation",
                ),
            ),
            Change("ebs", "ebs-1", "shared_dir", "vol1", "-", UpdatePolicy(UpdatePolicy.SUPPORTED)),
        ],
        UpdatePolicy.UNSUPPORTED,
    )


def _test_more_target_sections(base_conf, target_conf):
    # Remove an ebs section into the base conf
    assert_that(base_conf.get_section("ebs", "ebs-1")).is_not_none()
    base_conf.remove_section("ebs", "ebs-1")
    assert_that(base_conf.get_section("ebs", "ebs-1")).is_none()

    # The patch must show 2 differences: one for ebs_settings and one for missing ebs section in base conf
    _check_patch(
        base_conf,
        target_conf,
        [
            Change(
                "cluster",
                "default",
                "ebs_settings",
                "ebs-2",
                "ebs-1,ebs-2",
                UpdatePolicy(
                    UpdatePolicy.UNSUPPORTED,
                    fail_reason="EBS sections cannot be added or removed during a 'pcluster update' operation",
                ),
            ),
            Change("ebs", "ebs-1", "shared_dir", "-", "vol1", UpdatePolicy(UpdatePolicy.SUPPORTED)),
        ],
        UpdatePolicy.UNSUPPORTED,
    )


def _test_incompatible_ebs_sections(base_conf, target_conf):
    # Change shared_dir param value in target conf
    target_conf.get_section("ebs", "ebs-1").get_param("shared_dir").value = "new_value"

    # The patch must show the updated shared_dir for ebs-1 section
    _check_patch(
        base_conf,
        target_conf,
        [Change("ebs", "ebs-1", "shared_dir", "vol1", "new_value", UpdatePolicy(UpdatePolicy.UNSUPPORTED))],
        UpdatePolicy.UNSUPPORTED,
    )


def _test_different_labels(base_conf, target_conf):
    # First make sure sections are present with original labels

    base_ebs_1_section = base_conf.get_section("ebs", "ebs-1")
    base_ebs_2_section = base_conf.get_section("ebs", "ebs-2")

    assert_that(base_ebs_1_section).is_not_none()
    assert_that(base_ebs_2_section).is_not_none()

    # Now update section labels and make sure they're not more present with original labels
    base_ebs_1_section.label = "ebs-1_updated"
    base_ebs_2_section.label = "ebs-2_updated"

    assert_that(base_conf.get_section("ebs", "ebs-1_updated")).is_not_none()
    assert_that(base_conf.get_section("ebs", "ebs-2_updated")).is_not_none()
    assert_that(base_conf.get_section("ebs", "ebs-1")).is_none()
    assert_that(base_conf.get_section("ebs", "ebs-2")).is_none()

    # The patch should contain 5 differences:
    # - 2 volumes in target conf not matched in base conf
    # - 2 volumes in base conf not matched in target conf
    # - 1 ebs_settings changed in cluster section
    _check_patch(
        base_conf,
        target_conf,
        [
            Change("ebs", "ebs-1", "shared_dir", "-", "vol1", UpdatePolicy(UpdatePolicy.SUPPORTED)),
            Change("ebs", "ebs-1_updated", "shared_dir", "vol1", "-", UpdatePolicy(UpdatePolicy.SUPPORTED)),
            Change("ebs", "ebs-2", "shared_dir", "-", "vol2", UpdatePolicy(UpdatePolicy.SUPPORTED)),
            Change("ebs", "ebs-2_updated", "shared_dir", "vol2", "-", UpdatePolicy(UpdatePolicy.SUPPORTED)),
            Change(
                "cluster",
                "default",
                "ebs_settings",
                "ebs-1_updated,ebs-2_updated",
                "ebs-1,ebs-2",
                UpdatePolicy(
                    UpdatePolicy.UNSUPPORTED,
                    fail_reason="EBS sections cannot be added or removed during a 'pcluster update' operation",
                ),
            ),
        ],
        UpdatePolicy.UNSUPPORTED,
    )


@pytest.mark.parametrize(
    "test",
    [
        _test_less_target_sections,
        _test_more_target_sections,
        _test_incompatible_ebs_sections,
        _test_equal_configs,
        _test_different_labels,
    ],
)
def test_adaptation(mocker, test_datadir, pcluster_config_reader, test):
    _do_mocking_for_tests(mocker)
    base_config_file_name = "pcluster.config.base.ini"
    duplicate_config_file(base_config_file_name, test_datadir)
    target_config_file_name = "pcluster.config.dst.ini"
    duplicate_config_file(target_config_file_name, test_datadir)

    base_config_file = pcluster_config_reader(base_config_file_name, **default_cluster_params)
    target_config_file = pcluster_config_reader(target_config_file_name, **default_cluster_params)

    base_conf = PclusterConfig(config_file=base_config_file, fail_on_file_absence=True)
    target_conf = PclusterConfig(config_file=target_config_file, fail_on_file_absence=True)

    test(base_conf, target_conf)
