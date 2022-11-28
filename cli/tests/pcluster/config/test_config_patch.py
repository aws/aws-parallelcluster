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
import os

import pytest
from assertpy import assert_that

from pcluster.config.config_patch import Change, ConfigPatch
from pcluster.config.pcluster_config import PclusterConfig
from pcluster.config.update_policy import UpdatePolicy, _check_unmanaged_fsx
from pcluster.utils import InstanceTypeInfo
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
    mocker.patch(
        "pcluster.config.cfn_param_types.InstanceTypeInfo.init_from_instance_type",
        return_value=InstanceTypeInfo(
            {
                "InstanceType": "g4dn.metal",
                "VCpuInfo": {"DefaultVCpus": 96, "DefaultCores": 48, "DefaultThreadsPerCore": 2},
                "NetworkInfo": {"EfaSupported": True, "MaximumNetworkCards": 1},
            }
        ),
    )


def _check_patch(src_conf, dst_conf, expected_changes, expected_patch_policy):
    patch = ConfigPatch(base_config=src_conf, target_config=dst_conf)
    ignored_params = ["cluster_config_metadata"]

    changes = [change for change in patch.changes if change.param_key not in ignored_params]
    assert_that(sorted(changes)).is_equal_to(sorted(expected_changes))
    assert_that(patch.update_policy_level).is_equal_to(expected_patch_policy.level)


def test_config_patch(mocker):
    _do_mocking_for_tests(mocker)
    # We need to provide a region to PclusterConfig to avoid no region exception.
    # Which region to provide is arbitrary.
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    src_conf = PclusterConfig()
    dst_conf = PclusterConfig()
    # Two new configs must always be equal
    _check_patch(src_conf, dst_conf, [], UpdatePolicy.SUPPORTED)


@pytest.mark.parametrize(
    "section_key, section_label, param_key, src_param_value, dst_param_value, change_update_policy",
    [
        ("vpc", "default", "master_subnet_id", "subnet-12345678", "subnet-1234567a", UpdatePolicy.UNSUPPORTED),
        ("vpc", "default", "additional_sg", "sg-12345678", "sg-1234567a", UpdatePolicy.SUPPORTED),
        ("vpc", "default", "vpc_security_group_id", "sg-12345678", "sg-1234567a", UpdatePolicy.MANAGED_FSX),
        ("cluster", "default", "initial_queue_size", 0, 1, UpdatePolicy.SUPPORTED),
        ("cluster", "default", "max_queue_size", 0, 1, UpdatePolicy.MAX_QUEUE_SIZE),
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


@pytest.mark.parametrize(
    "src_cluster_label, dst_cluster_label",
    [  # If label of cluster section is changed, change check should still work
        ("default", "default"),
        ("default", "default2"),
        ("defualt2", "default"),
    ],
)
def test_multiple_param_changes(mocker, pcluster_config_reader, test_datadir, src_cluster_label, dst_cluster_label):
    _do_mocking_for_tests(mocker)
    dst_config_file = "pcluster.config.dst.ini"
    duplicate_config_file(dst_config_file, test_datadir)

    src_dict = {}
    src_dict.update(default_cluster_params)
    src_dict["cluster_label"] = src_cluster_label
    src_dict["master_subnet_id"] = "subnet-12345678"
    src_dict["compute_subnet_id"] = "subnet-12345678"
    src_dict["additional_sg"] = "sg-12345678"

    src_config_file = pcluster_config_reader(**src_dict)
    src_conf = PclusterConfig(config_file=src_config_file, fail_on_file_absence=True)

    dst_dict = {}
    dst_dict.update(default_cluster_params)
    dst_dict["cluster_label"] = dst_cluster_label
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
            Change("ebs", "ebs-1", "volume_size", 20, "-", UpdatePolicy(UpdatePolicy.SUPPORTED)),
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
            Change("ebs", "ebs-1", "volume_size", "-", 20, UpdatePolicy(UpdatePolicy.SUPPORTED)),
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
            Change("ebs", "ebs-1", "volume_size", "-", 20, UpdatePolicy(UpdatePolicy.SUPPORTED)),
            Change("ebs", "ebs-1_updated", "volume_size", 20, "-", UpdatePolicy(UpdatePolicy.SUPPORTED)),
            Change("ebs", "ebs-2", "volume_size", "-", 20, UpdatePolicy(UpdatePolicy.SUPPORTED)),
            Change("ebs", "ebs-2_updated", "volume_size", 20, "-", UpdatePolicy(UpdatePolicy.SUPPORTED)),
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


@pytest.mark.parametrize(
    ("old_bucket_name", "new_bucket_name", "is_generated_bucket", "expected_error_row"),
    [
        # pcluster generated bucket, got old value from CFN, no new value in update config
        # Proceed with update without printing diff
        ("parallelcluster-generated-bucket", None, True, False),
        # pcluster generated bucket, no old value for some reason, no new value in update config
        # Proceed with update, no diff
        (None, None, True, False),
        # pcluster generated bucket, got old value from CFN, specifies generated bucket in update config
        # Proceed with update, no diff
        ("parallelcluster-generated-bucket", "parallelcluster-generated-bucket", True, False),
        # pcluster generated bucket, got old value from CFN, specifies different bucket in update config
        # Block update, print diff
        ("parallelcluster-generated-bucket", "user-provided-bucket", True, True),
        # user-provided-bucket in old config, no bucket specified in update config
        # Block update, print diff
        ("user-provided-bucket", None, False, True),
        # user-provided-bucket in old config, different bucket specified in update config
        # Block update, print diff
        ("user-provided-bucket-old", "user-provided-bucket-new", False, True),
        # user-provided-bucket in old config, same bucket specified in update config
        # Proceed with update, no diff
        ("user-provided-bucket-consistent", "user-provided-bucket-consistent", False, False),
    ],
)
def test_patch_check_cluster_resource_bucket(
    old_bucket_name,
    new_bucket_name,
    is_generated_bucket,
    expected_error_row,
    mocker,
    test_datadir,
    pcluster_config_reader,
):
    _do_mocking_for_tests(mocker)
    mocker.patch("pcluster.config.update_policy._is_bucket_pcluster_generated", return_value=is_generated_bucket)
    expected_message_rows = [
        ["section", "parameter", "old value", "new value", "check", "reason", "action_needed"],
        # iam_lambda_role is to make sure other parameters are not affected by cluster_resource_bucket custom logic
        ["cluster some_cluster", "iam_lambda_role", "some_old_role", "some_new_role", "SUCCEEDED", "-", None],
    ]
    if expected_error_row:
        error_message_row = [
            "cluster some_cluster",
            "cluster_resource_bucket",
            old_bucket_name,
            new_bucket_name,
            "ACTION NEEDED",
            (
                "'cluster_resource_bucket' parameter is a read_only parameter that cannot be updated. "
                "New value '{0}' will be ignored and old value '{1}' will be used if you force the update.".format(
                    new_bucket_name, old_bucket_name
                )
            ),
            "Restore the value of parameter 'cluster_resource_bucket' to '{0}'".format(old_bucket_name),
        ]
        expected_message_rows.append(error_message_row)
    src_dict = {"cluster_resource_bucket": old_bucket_name, "iam_lambda_role": "some_old_role"}
    dst_dict = {"cluster_resource_bucket": new_bucket_name, "iam_lambda_role": "some_new_role"}
    dst_config_file = "pcluster.config.dst.ini"
    duplicate_config_file(dst_config_file, test_datadir)

    src_config_file = pcluster_config_reader(**src_dict)
    src_conf = PclusterConfig(config_file=src_config_file, fail_on_file_absence=True)
    dst_config_file = pcluster_config_reader(dst_config_file, **dst_dict)
    dst_conf = PclusterConfig(config_file=dst_config_file, fail_on_file_absence=True)
    patch = ConfigPatch(base_config=src_conf, target_config=dst_conf)

    patch_allowed, rows = patch.check()
    assert_that(len(rows)).is_equal_to(len(expected_message_rows))
    for line in rows:
        # Handle unicode string
        line = ["{0}".format(element) if isinstance(element, str) else element for element in line]
        assert_that(expected_message_rows).contains(line)
    assert_that(patch_allowed).is_equal_to(not expected_error_row)


@pytest.mark.parametrize(
    "fsx_options, is_unmanaged_fsx",
    [
        ("NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE", False),
        (
            "shared_dir,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
            False,
        ),
        (
            "shared_dir,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,"
            "NONE,NONE,NONE,NONE,fsx_backup_id,NONE,NONE,NONE,NONE,NONE,NONE",
            False,
        ),
        (
            "shared_dir,fsx_fs_id,NONE,NONE,NONE,NONE,NONE,NONE,NONE,"
            "NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE,NONE",
            True,
        ),
        (
            "shared_dir,fsx_fs_id,storage_capacity,fsx_kms_key_id,imported_file_chunk_size,export_path,"
            "import_path,weekly_maintenance_start_time,deployment_type,per_unit_storage_throughput,"
            "daily_automatic_backup_start_time,automatic_backup_retention_days,copy_tags_to_backups,"
            "fsx_backup_id,auto_import_policy,storage_type,drive_cache_type,existing_mount_name,"
            "existing_dns_name,data_compression_type",
            True,
        ),
        (
            "shared_dir,NONE,storage_capacity,fsx_kms_key_id,imported_file_chunk_size,export_path,"
            "import_path,weekly_maintenance_start_time,deployment_type,per_unit_storage_throughput,"
            "daily_automatic_backup_start_time,automatic_backup_retention_days,copy_tags_to_backups,"
            "fsx_backup_id,auto_import_policy,storage_type,drive_cache_type,existing_mount_name,"
            "existing_dns_name,data_compression_type",
            False,
        ),
    ],
)
def test_check_unmanaged_fsx(fsx_options, is_unmanaged_fsx, pcluster_config_reader, mocker):
    mocked_cfn_params = {"Parameters": [{"ParameterKey": "FSXOptions", "ParameterValue": fsx_options}]}
    get_stack_mock = mocker.patch("pcluster.utils.get_stack", return_value=mocked_cfn_params)

    patch_mock = mocker.MagicMock()
    patch_mock.stack_name = "stack_name"

    assert_that(_check_unmanaged_fsx(None, patch_mock)).is_equal_to(is_unmanaged_fsx)
    get_stack_mock.assert_called_with("stack_name")


@pytest.mark.parametrize(
    "src_value, dst_value, is_managed_fsx, expected_update_policy, expected_patch_allowed",
    [
        # no changes in vpc_security_group_id
        (None, None, True, UpdatePolicy.SUPPORTED, True),
        (None, None, False, UpdatePolicy.SUPPORTED, True),
        ("sg-12345678", "sg-12345678", True, UpdatePolicy.SUPPORTED, True),
        ("sg-12345678", "sg-12345678", False, UpdatePolicy.SUPPORTED, True),
        # changes in vpc_security_group_id
        (None, "sg-12345678", True, UpdatePolicy.MANAGED_FSX, False),
        (None, "sg-12345678", False, UpdatePolicy.MANAGED_FSX, True),
        ("sg-12345678", "sg-23456789", True, UpdatePolicy.MANAGED_FSX, False),
        ("sg-12345678", "sg-23456789", False, UpdatePolicy.MANAGED_FSX, True),
        ("sg-12345678", None, True, UpdatePolicy.MANAGED_FSX, False),
        ("sg-12345678", None, False, UpdatePolicy.MANAGED_FSX, True),
    ],
)
def test_vpc_security_id_changes(
    mocker,
    pcluster_config_reader,
    test_datadir,
    src_value,
    dst_value,
    is_managed_fsx,
    expected_update_policy,
    expected_patch_allowed,
):
    _do_mocking_for_tests(mocker)
    fsx_options = ["shared_dir", "NONE", "..."] if is_managed_fsx else ["shared_dir", "fsx_fs_id", "..."]
    mocker.patch("pcluster.config.update_policy._get_fsx_options", return_value=fsx_options)

    dst_config_file = "pcluster.config.dst.ini"
    duplicate_config_file(dst_config_file, test_datadir)

    src_config_file = pcluster_config_reader(**{"vpc_security_group_id": src_value})
    src_conf = PclusterConfig(config_file=src_config_file, fail_on_file_absence=True)

    dst_config_file = pcluster_config_reader(dst_config_file, **{"vpc_security_group_id": dst_value})
    dst_conf = PclusterConfig(config_file=dst_config_file, fail_on_file_absence=True)

    expected_changes = []
    expected_message_rows = [["section", "parameter", "old value", "new value", "check", "reason", "action_needed"]]
    if src_value != dst_value:
        expected_changes.append(
            Change("vpc", "default", "vpc_security_group_id", src_value, dst_value, UpdatePolicy.MANAGED_FSX),
        )
        if expected_patch_allowed:
            check = "SUCCEEDED"
            reason = "-"
            action_needed = None
        else:
            check = "ACTION NEEDED"
            reason = (
                "'vpc_security_group_id' parameter cannot be updated because the cluster was created with a "
                "managed FSx. The change in the 'vpc_security_group_id' will trigger a creation of a new file system "
                "to replace the old one, without preserving the existing data. If you force the update you'll lose "
                "your data. Make sure to back up the data from the existing FSx for Lustre file system "
                "if you want to preserve them. For more information, see "
                "https://docs.aws.amazon.com/fsx/latest/LustreGuide/using-backups-fsx.html"
            )
            action_needed = (
                f"Restore the value of parameter 'vpc_security_group_id' to '{src_value}'"
                if src_value
                else "Remove the parameter 'vpc_security_group_id'"
            )

        expected_message_rows.append(
            ["vpc default", "vpc_security_group_id", src_value, dst_value, check, reason, action_needed]
        )

    _check_patch(src_conf, dst_conf, expected_changes, expected_update_policy)
    is_patch_allowed, rows = ConfigPatch(base_config=src_conf, target_config=dst_conf).check()
    assert_that(expected_patch_allowed).is_equal_to(is_patch_allowed)

    for line in expected_message_rows:
        # Handle unicode string
        line = ["{0}".format(element) if isinstance(element, str) else element for element in line]
        assert_that(rows).contains(line)
