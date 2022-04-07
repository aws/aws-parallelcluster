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
import shutil

import pytest
from assertpy import assert_that

from pcluster.config.cluster_config import QueueUpdateStrategy
from pcluster.config.config_patch import Change, ConfigPatch
from pcluster.config.update_policy import UpdatePolicy
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.utils import load_yaml_dict
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.test_utils import dummy_cluster

default_cluster_params = {
    "custom_ami": "ami-12345678",
    "head_node_custom_ami": "ami-12345678",
    "queue_custom_ami": "ami-12345678",
    "head_node_subnet_id": "subnet-12345678",
    "compute_subnet_id": "subnet-12345678",
    "additional_sg": "sg-12345678",
    "max_count": 10,
    "compute_instance_type": "t2.micro",
    "shared_dir": "mountdir1",
    "ebs_encrypted": True,
}


def _duplicate_config_file(dst_config_file, test_datadir):
    """
    Make a copy of the src template to the target file.

    The two resulting PClusterConfig instances will be identical.
    """
    src_config_file_path = os.path.join(str(test_datadir), "pcluster.config.yaml")
    dst_config_file_path = os.path.join(str(test_datadir), dst_config_file)
    shutil.copy(src_config_file_path, dst_config_file_path)


def _check_patch(src_conf, dst_conf, expected_changes, expected_patch_policy):
    patch = ConfigPatch(dummy_cluster(), base_config=src_conf, target_config=dst_conf)

    _compare_changes(patch.changes, expected_changes)
    assert_that(patch.update_policy_level).is_equal_to(expected_patch_policy.level)


def _compare_changes(changes, expected_changes):
    def _compare_change(source, target):
        return (
            source.path == target.path
            and source.key == target.key
            and source.old_value == target.old_value
            and source.new_value == target.new_value
            and source.update_policy.level == target.update_policy.level
            and source.update_policy.fail_reason == target.update_policy.fail_reason
            and source.is_list == target.is_list
        )

    sorted_changes = sorted(changes, key=lambda change: change.key)
    sorted_expected_changes = sorted(expected_changes, key=lambda change: change.key)

    assert_that(
        all([_compare_change(source, target) for source, target in zip(sorted_changes, sorted_expected_changes)])
    ).is_true()


@pytest.mark.parametrize(
    "change_path, template_rendering_key, param_key, src_param_value, dst_param_value, change_update_policy, is_list",
    [
        pytest.param(
            ["HeadNode", "Networking"],
            "head_node_subnet_id",
            "SubnetId",
            "subnet-12345678",
            "subnet-1234567a",
            UpdatePolicy.UNSUPPORTED,
            False,
            id="change subnet id",
        ),
        pytest.param(
            ["HeadNode", "Networking"],
            "additional_sg",
            "AdditionalSecurityGroups",
            "sg-12345678",
            "sg-1234567a",
            UpdatePolicy.SUPPORTED,
            True,
            id="change additional security group",
        ),
        pytest.param(
            ["Image"],
            "custom_ami",
            "CustomAmi",
            "ami-12345678",
            "ami-1234567a",
            UpdatePolicy.UNSUPPORTED,
            False,
            id="change top level custom ami",
        ),
        pytest.param(
            ["HeadNode", "Image"],
            "head_node_custom_ami",
            "CustomAmi",
            "ami-12345678",
            "ami-1234567a",
            UpdatePolicy.UNSUPPORTED,
            False,
            id="change head node custom ami",
        ),
        pytest.param(
            ["Scheduling", "SlurmQueues[queue1]", "Image"],
            "queue_custom_ami",
            "CustomAmi",
            "ami-12345678",
            "ami-1234567a",
            UpdatePolicy.COMPUTE_FLEET_STOP,
            False,
            id="change queue custom ami",
        ),
        pytest.param(
            ["SharedStorage[ebs1]", "EbsSettings"],
            "ebs_encrypted",
            "Encrypted",
            True,
            False,
            UpdatePolicy.UNSUPPORTED,
            False,
            id="change ebs settings encrypted",
        ),
        pytest.param(
            ["Scheduling", "SlurmQueues[queue1]", "ComputeResources[compute-resource1]"],
            "max_count",
            "MaxCount",
            1,
            2,
            UpdatePolicy.MAX_COUNT,
            False,
            id="change compute resources max count",
        ),
        pytest.param(
            ["Scheduling", "SlurmQueues[queue1]", "ComputeResources[compute-resource1]"],
            "compute_instance_type",
            "InstanceType",
            "t2.micro",
            "c4.xlarge",
            UpdatePolicy.COMPUTE_FLEET_STOP,
            False,
            id="change compute resources instance type",
        ),
        pytest.param(
            ["HeadNode", "Iam"],
            "head_node_instance_profile",
            "InstanceProfile",
            "arn:aws:iam::aws:instance-profile/InstanceProfileone",
            "arn:aws:iam::aws:instance-profile/InstanceProfiletwo",
            UpdatePolicy.UNSUPPORTED,
            False,
            id="change head node instance profile",
        ),
        pytest.param(
            ["Scheduling", "SlurmQueues[queue1]", "Iam"],
            "queue_instance_profile",
            "InstanceProfile",
            "arn:aws:iam::aws:instance-profile/InstanceProfileone",
            "arn:aws:iam::aws:instance-profile/InstanceProfiletwo",
            UpdatePolicy.SUPPORTED,
            False,
            id="change queue insatnce profile",
        ),
    ],
)
def test_single_param_change(
    mocker,
    test_datadir,
    pcluster_config_reader,
    change_path,
    template_rendering_key,
    param_key,
    src_param_value,
    dst_param_value,
    change_update_policy,
    is_list,
):
    mock_aws_api(mocker)
    dst_config_file = "pcluster.config.dst.yaml"
    _duplicate_config_file(dst_config_file, test_datadir)

    src_dict = {}
    src_dict.update(default_cluster_params)
    src_dict[template_rendering_key] = src_param_value

    src_config_file = pcluster_config_reader(**src_dict)
    src_conf = _load_config(src_config_file)

    dst_dict = {}
    dst_dict.update(default_cluster_params)
    dst_dict[template_rendering_key] = dst_param_value
    dst_config_file = pcluster_config_reader(dst_config_file, **dst_dict)
    dst_conf = _load_config(dst_config_file)

    if is_list:
        expected_change = Change(
            change_path, param_key, [src_param_value], [dst_param_value], change_update_policy, is_list=False
        )
    else:
        expected_change = Change(
            change_path, param_key, src_param_value, dst_param_value, change_update_policy, is_list=False
        )
    _check_patch(src_conf.source_config, dst_conf.source_config, [expected_change], change_update_policy)


def _load_config(config_file):
    return ClusterSchema(cluster_name="clustername").load(load_yaml_dict(config_file))


def test_multiple_param_changes(mocker, pcluster_config_reader, test_datadir):
    mock_aws_api(mocker)
    dst_config_file = "pcluster.config.dst.yaml"
    _duplicate_config_file(dst_config_file, test_datadir)

    src_dict = {}
    src_dict.update(default_cluster_params)
    src_dict["head_node_subnet_id"] = "subnet-12345678"
    src_dict["compute_subnet_id"] = "subnet-12345678"
    src_dict["additional_sg"] = "sg-12345678"

    src_config_file = pcluster_config_reader(**src_dict)
    src_conf = _load_config(src_config_file)

    dst_dict = {}
    dst_dict.update(default_cluster_params)
    dst_dict["head_node_subnet_id"] = "subnet-1234567a"
    dst_dict["compute_subnet_id"] = "subnet-1234567a"
    dst_dict["additional_sg"] = "sg-1234567a"

    dst_config_file = pcluster_config_reader(dst_config_file, **dst_dict)
    dst_conf = _load_config(dst_config_file)

    expected_changes = [
        Change(
            ["HeadNode", "Networking"],
            "SubnetId",
            "subnet-12345678",
            "subnet-1234567a",
            UpdatePolicy.UNSUPPORTED,
            is_list=False,
        ),
        Change(
            ["Scheduling", "SlurmQueues[queue1]", "Networking"],
            "SubnetIds",
            ["subnet-12345678"],
            ["subnet-1234567a"],
            UpdatePolicy.COMPUTE_FLEET_STOP,
            is_list=False,
        ),
        Change(
            ["HeadNode", "Networking"],
            "AdditionalSecurityGroups",
            ["sg-12345678"],
            ["sg-1234567a"],
            UpdatePolicy.SUPPORTED,
            is_list=False,
        ),
    ]

    _check_patch(src_conf.source_config, dst_conf.source_config, expected_changes, UpdatePolicy.UNSUPPORTED)


def _test_equal_configs(base_conf, target_conf):
    # Without doing any changes the two configs must be equal
    _check_patch(base_conf, target_conf, [], UpdatePolicy.SUPPORTED)


def _test_less_target_sections(base_conf, target_conf):
    # Remove an ebs section in the target conf
    assert_that(_get_storage_by_name(target_conf, "ebs1")).is_not_none()
    _remove_storage_by_name(target_conf, "ebs1")
    assert_that(_get_storage_by_name(target_conf, "ebs1")).is_none()

    # add new section + param in the base conf so that it appears as removed in the target conf
    base_conf["Scheduling"].update({"SlurmSettings": {"ScaledownIdletime": 30}})
    base_conf["Scheduling"]["SlurmSettings"].update({"QueueUpdateStrategy": QueueUpdateStrategy.DRAIN.value})

    # add new param in the base conf so that it appears as removed in the target conf
    base_conf["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MinCount"] = 1

    # update some values in the target config for the remaining ebs
    target_conf["SharedStorage"][0]["MountDir"] = "vol1"
    target_conf["SharedStorage"][0]["EbsSettings"]["Iops"] = 20
    target_conf["SharedStorage"][0]["EbsSettings"]["VolumeType"] = "gp2"

    # The patch must show multiple differences: one for EBS settings and one for missing ebs section in target conf
    _check_patch(
        base_conf,
        target_conf,
        [
            Change(
                [],
                "SharedStorage",
                _get_storage_by_name(base_conf, "ebs1"),
                None,
                UpdatePolicy(
                    UpdatePolicy.UNSUPPORTED,
                    name="UNSUPPORTED",
                    fail_reason=(
                        "Shared Storage cannot be added or removed during a 'pcluster update-cluster' operation"
                    ),
                ),
                is_list=True,
            ),
            Change(["SharedStorage[ebs2]"], "MountDir", "vol2", "vol1", UpdatePolicy.UNSUPPORTED, is_list=False),
            Change(["SharedStorage[ebs2]", "EbsSettings"], "Iops", None, 20, UpdatePolicy.SUPPORTED, is_list=False),
            Change(
                ["SharedStorage[ebs2]", "EbsSettings"],
                "VolumeType",
                "gp3",
                "gp2",
                UpdatePolicy.UNSUPPORTED,
                is_list=False,
            ),
            Change(
                ["Scheduling"],
                "SlurmSettings",
                {"ScaledownIdletime": 30, "QueueUpdateStrategy": QueueUpdateStrategy.DRAIN.value},
                "-",
                UpdatePolicy.IGNORED,
                is_list=False,
            ),
            Change(
                ["Scheduling", "SlurmSettings"],
                "ScaledownIdletime",
                30,
                None,
                UpdatePolicy.COMPUTE_FLEET_STOP,
                is_list=False,
            ),
            Change(
                ["Scheduling", "SlurmQueues[queue1]", "ComputeResources[compute-resource1]"],
                "MinCount",
                1,
                None,
                UpdatePolicy.COMPUTE_FLEET_STOP,
                is_list=False,
            ),
            Change(
                ["Scheduling", "SlurmSettings"],
                "QueueUpdateStrategy",
                QueueUpdateStrategy.DRAIN.value,
                None,
                UpdatePolicy.IGNORED,
                is_list=False,
            ),
        ],
        UpdatePolicy.UNSUPPORTED,
    )


def _get_storage_by_name(target_conf: dict, name: str):
    return next(iter(ebs for ebs in target_conf["SharedStorage"] if ebs["Name"] == name), None)


def _remove_storage_by_name(target_conf: dict, name: str):
    for index in range(len(target_conf["SharedStorage"])):
        if target_conf["SharedStorage"][index]["Name"] == name:
            del target_conf["SharedStorage"][index]
        break


def _test_more_target_sections(base_conf, target_conf):
    # Remove an ebs section into the base conf
    assert_that(_get_storage_by_name(base_conf, "ebs1")).is_not_none()
    _remove_storage_by_name(base_conf, "ebs1")
    assert_that(_get_storage_by_name(base_conf, "ebs1")).is_none()

    # update some values in the target config for the remaining ebs
    target_storage = _get_storage_by_name(target_conf, "ebs2")
    target_storage["MountDir"] = "vol1"
    target_storage["EbsSettings"]["Iops"] = 20
    target_storage["EbsSettings"]["VolumeType"] = "gp2"

    # add new section + param in the target conf
    target_conf["Scheduling"].update({"SlurmSettings": {"ScaledownIdletime": 30}})
    target_conf["Scheduling"]["SlurmSettings"].update(
        {"QueueUpdateStrategy": QueueUpdateStrategy.COMPUTE_FLEET_STOP.value}
    )

    # add new param in the target conf
    target_conf["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MinCount"] = 1

    # The patch must show multiple differences: changes for EBS settings and one for missing ebs section in base conf
    _check_patch(
        base_conf,
        target_conf,
        [
            Change(
                [],
                "SharedStorage",
                None,
                _get_storage_by_name(target_conf, "ebs1"),
                UpdatePolicy(
                    UpdatePolicy.UNSUPPORTED,
                    fail_reason=(
                        "Shared Storage cannot be added or removed during a 'pcluster update-cluster' operation"
                    ),
                ),
                is_list=True,
            ),
            Change(["SharedStorage[ebs2]"], "MountDir", "vol2", "vol1", UpdatePolicy.UNSUPPORTED, is_list=False),
            Change(["SharedStorage[ebs2]", "EbsSettings"], "Iops", None, 20, UpdatePolicy.SUPPORTED, is_list=False),
            Change(
                ["SharedStorage[ebs2]", "EbsSettings"],
                "VolumeType",
                "gp3",
                "gp2",
                UpdatePolicy.UNSUPPORTED,
                is_list=False,
            ),
            Change(
                ["Scheduling"],
                "SlurmSettings",
                "-",
                {"ScaledownIdletime": 30, "QueueUpdateStrategy": QueueUpdateStrategy.COMPUTE_FLEET_STOP.value},
                UpdatePolicy.IGNORED,
                is_list=False,
            ),
            Change(
                ["Scheduling", "SlurmSettings"],
                "ScaledownIdletime",
                None,
                30,
                UpdatePolicy.COMPUTE_FLEET_STOP,
                is_list=False,
            ),
            Change(
                ["Scheduling", "SlurmQueues[queue1]", "ComputeResources[compute-resource1]"],
                "MinCount",
                None,
                1,
                UpdatePolicy.COMPUTE_FLEET_STOP,
                is_list=False,
            ),
            Change(
                ["Scheduling", "SlurmSettings"],
                "QueueUpdateStrategy",
                None,
                QueueUpdateStrategy.COMPUTE_FLEET_STOP.value,
                UpdatePolicy.IGNORED,
                is_list=False,
            ),
        ],
        UpdatePolicy.UNSUPPORTED,
    )


def _test_incompatible_ebs_sections(base_conf, target_conf):
    # Change MountDir param value in target conf
    _get_storage_by_name(target_conf, "ebs1")["MountDir"] = "new_value"

    # The patch must show the updated MountDir for ebs1 section
    _check_patch(
        base_conf,
        target_conf,
        [
            Change(
                ["SharedStorage[ebs1]"], "MountDir", "vol1", "new_value", UpdatePolicy(UpdatePolicy.UNSUPPORTED), False
            )
        ],
        UpdatePolicy.UNSUPPORTED,
    )


def _test_different_names(base_conf, target_conf):
    # First make sure sections are present with original names
    base_ebs_1_section = _get_storage_by_name(base_conf, "ebs1")
    base_ebs_2_section = _get_storage_by_name(base_conf, "ebs2")
    assert_that(base_ebs_1_section).is_not_none()
    assert_that(base_ebs_2_section).is_not_none()

    target_ebs_1_section = _get_storage_by_name(target_conf, "ebs1")
    target_ebs_2_section = _get_storage_by_name(target_conf, "ebs2")
    assert_that(target_ebs_1_section).is_not_none()
    assert_that(target_ebs_2_section).is_not_none()

    # Now update section labels and make sure they're not more present with original labels
    target_ebs_1_section["Name"] = "ebs1_updated"
    target_ebs_2_section["Name"] = "ebs2_updated"
    assert_that(_get_storage_by_name(target_conf, "ebs1_updated")).is_not_none()
    assert_that(_get_storage_by_name(target_conf, "ebs2_updated")).is_not_none()
    assert_that(_get_storage_by_name(target_conf, "ebs1")).is_none()
    assert_that(_get_storage_by_name(target_conf, "ebs-")).is_none()

    unsupported_update_policy = UpdatePolicy(
        UpdatePolicy.UNSUPPORTED,
        fail_reason="Shared Storage cannot be added or removed during a 'pcluster update-cluster' operation",
    )

    # The patch should contain 5 differences:
    # - 2 volumes in target conf not matched in base conf
    # - 2 volumes in base conf not matched in target conf
    _check_patch(
        base_conf,
        target_conf,
        [
            Change([], "SharedStorage", None, target_ebs_1_section, unsupported_update_policy, is_list=True),
            Change([], "SharedStorage", None, target_ebs_2_section, unsupported_update_policy, is_list=True),
            Change([], "SharedStorage", base_ebs_1_section, None, unsupported_update_policy, is_list=True),
            Change([], "SharedStorage", base_ebs_2_section, None, unsupported_update_policy, is_list=True),
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
        _test_different_names,
    ],
)
def test_adaptation(mocker, test_datadir, pcluster_config_reader, test):
    mock_aws_api(mocker)
    base_config_file_name = "pcluster.config.base.yaml"
    _duplicate_config_file(base_config_file_name, test_datadir)
    target_config_file_name = "pcluster.config.dst.yaml"
    _duplicate_config_file(target_config_file_name, test_datadir)

    base_config_file = pcluster_config_reader(base_config_file_name, **default_cluster_params)
    target_config_file = pcluster_config_reader(target_config_file_name, **default_cluster_params)

    base_conf = _load_config(base_config_file)
    target_conf = _load_config(target_config_file)

    test(base_conf.source_config, target_conf.source_config)


@pytest.mark.parametrize(
    ("old_bucket_name", "new_bucket_name", "expected_error_row"),
    [
        # pcluster generated bucket, no old value in config, no new value in update config
        # Proceed with update, no diff
        (None, None, False),
        # user-provided-bucket in old config, no bucket specified in update config
        # Block update, print diff
        ("user-provided-bucket", None, True),
        # user-provided-bucket in old config, different bucket specified in update config
        # Block update, print diff
        ("user-provided-bucket-old", "user-provided-bucket-new", True),
        # user-provided-bucket in old config, same bucket specified in update config
        # Proceed with update, no diff
        ("user-provided-bucket-consistent", "user-provided-bucket-consistent", False),
    ],
)
def test_patch_check_cluster_resource_bucket(
    mocker,
    old_bucket_name,
    new_bucket_name,
    expected_error_row,
    test_datadir,
    pcluster_config_reader,
):
    mock_aws_api(mocker)
    expected_message_rows = [
        ["param_path", "parameter", "old value", "new value", "check", "reason", "action_needed", "update_policy"],
        # ec2_iam_role is to make sure other parameters are not affected by cluster_resource_bucket custom logic
        [
            ["HeadNode", "Iam"],
            "InstanceRole",
            "arn:aws:iam::aws:role/some_old_role",
            "arn:aws:iam::aws:role/some_new_role",
            "SUCCEEDED",
            "-",
            None,
            UpdatePolicy.SUPPORTED.name,
        ],
    ]
    if expected_error_row:
        error_message_row = [
            [],
            "CustomS3Bucket",
            old_bucket_name,
            new_bucket_name,
            "ACTION NEEDED",
            (
                "'CustomS3Bucket' parameter is a read only parameter that cannot be updated. "
                "New value '{0}' will be ignored and old value '{1}' will be used if you force the update.".format(
                    new_bucket_name, old_bucket_name
                )
            ),
            f"Restore the value of parameter 'CustomS3Bucket' to '{old_bucket_name}'",
            UpdatePolicy.READ_ONLY_RESOURCE_BUCKET.name,
        ]
        expected_message_rows.append(error_message_row)
    src_dict = {"cluster_resource_bucket": old_bucket_name, "ec2_iam_role": "arn:aws:iam::aws:role/some_old_role"}
    src_dict.update(default_cluster_params)
    dst_dict = {"cluster_resource_bucket": new_bucket_name, "ec2_iam_role": "arn:aws:iam::aws:role/some_new_role"}
    dst_dict.update(default_cluster_params)
    dst_config_file = "pcluster.config.dst.yaml"
    _duplicate_config_file(dst_config_file, test_datadir)

    src_config_file = pcluster_config_reader(**src_dict)
    src_conf = _load_config(src_config_file)
    dst_config_file = pcluster_config_reader(dst_config_file, **dst_dict)
    dst_conf = _load_config(dst_config_file)
    patch = ConfigPatch(dummy_cluster(), base_config=src_conf.source_config, target_config=dst_conf.source_config)

    patch_allowed, rows = patch.check()
    assert_that(len(rows)).is_equal_to(len(expected_message_rows))
    for line in rows:
        # Handle unicode string
        line = ["{0}".format(element) if isinstance(element, str) else element for element in line]
        assert_that(expected_message_rows).contains(line)
    assert_that(patch_allowed).is_equal_to(not expected_error_row)
