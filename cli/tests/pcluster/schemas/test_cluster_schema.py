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
import yaml
from assertpy import assert_that
from marshmallow.validate import ValidationError

from pcluster.constants import NODE_BOOTSTRAP_TIMEOUT
from pcluster.schemas.cluster_schema import (
    ClusterSchema,
    HeadNodeCustomActionsSchema,
    HeadNodeIamSchema,
    HeadNodeRootVolumeSchema,
    ImageSchema,
    QueueCustomActionsSchema,
    QueueIamSchema,
    QueueTagSchema,
    SchedulingSchema,
    SharedStorageSchema,
    SlurmQueueSchema,
    TimeoutsSchema,
)
from pcluster.utils import replace_url_parameters
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.utils import load_cluster_model_from_yaml


def _check_cluster_schema(config_file_name):
    # Load cluster model from Yaml file
    input_yaml, cluster = load_cluster_model_from_yaml(config_file_name)

    # Re-create Yaml file from model and compare content
    cluster_schema = ClusterSchema(cluster_name="clustername")
    cluster_schema.context = {"delete_defaults_when_dump": True}
    output_json = cluster_schema.dump(cluster)
    assert_that(replace_url_parameters(json.dumps(input_yaml, sort_keys=True))).is_equal_to(
        json.dumps(output_json, sort_keys=True)
    )

    # Print output yaml
    output_yaml = yaml.dump(output_json)
    print(output_yaml)


@pytest.mark.parametrize("config_file_name", ["slurm.required.yaml", "slurm.full.yaml"])
def test_cluster_schema_slurm(mocker, test_datadir, config_file_name):
    mock_aws_api(mocker)
    mocker.patch("pcluster.utils.get_region", return_value="fake_region")
    _check_cluster_schema(config_file_name)


@pytest.mark.parametrize("config_file_name", ["awsbatch.simple.yaml", "awsbatch.full.yaml"])
def test_cluster_schema_awsbatch(mocker, test_datadir, config_file_name):
    mock_aws_api(mocker)
    mocker.patch("pcluster.utils.get_region", return_value="fake_region")
    _check_cluster_schema(config_file_name)


@pytest.mark.parametrize(
    "os, custom_ami, failure_message",
    [
        (None, None, "Missing data for required field"),
        ("ubuntu1804", "ami-12345678", None),
        ("centos7", None, None),
    ],
)
def test_image_schema(os, custom_ami, failure_message):
    image_schema = {}
    if os:
        image_schema["Os"] = os
    if custom_ami:
        image_schema["CustomAmi"] = custom_ami

    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            ImageSchema().load(image_schema)
    else:
        image = ImageSchema().load(image_schema)
        assert_that(image.os).is_equal_to(os)
        assert_that(image.custom_ami).is_equal_to(custom_ami)


@pytest.mark.parametrize(
    "instance_role, instance_profile, additional_iam_policies, s3_access, failure_message",
    [
        (None, None, "arn:aws:iam::aws:policy/AdministratorAccess", True, False),
        (
            "arn:aws:iam::aws:role/CustomHeadNodeRole",
            None,
            "arn:aws:iam::aws:policy/AdministratorAccess",
            False,
            "InstanceProfile, InstanceRole or AdditionalIamPolicies can not be configured together.",
        ),
        (
            "arn:aws:iam::aws:role/CustomHeadNodeRole",
            None,
            None,
            True,
            "S3Access can not be configured when InstanceRole is set.",
        ),
        (
            None,
            "arn:aws:iam::aws:instance-profile/CustomNodeInstanceProfile",
            None,
            True,
            "S3Access can not be configured when InstanceProfile is set.",
        ),
        (
            "arn:aws:iam::aws:role/CustomHeadNodeRole",
            "arn:aws:iam::aws:instance-profile/CustomNodeInstanceProfile",
            None,
            False,
            "InstanceProfile, InstanceRole or AdditionalIamPolicies can not be configured together.",
        ),
        (None, "arn:aws:iam::aws:instance-profile/CustomNodeInstanceProfile", None, False, False),
        ("arn:aws:iam::aws:role/CustomHeadNodeRole", None, None, False, False),
    ],
)
def test_iam_schema(instance_role, instance_profile, additional_iam_policies, s3_access, failure_message):
    iam_dict = dict()
    if instance_role:
        iam_dict["InstanceRole"] = instance_role
    if instance_profile:
        iam_dict["InstanceProfile"] = instance_profile
    if additional_iam_policies:
        iam_dict["AdditionalIamPolicies"] = [{"Policy": additional_iam_policies}]
    if s3_access:
        iam_dict["S3Access"] = [{"BucketName": "dummy-bucket-name"}]

    if failure_message:
        with pytest.raises(
            ValidationError,
            match=failure_message,
        ):
            HeadNodeIamSchema().load(iam_dict)
        with pytest.raises(
            ValidationError,
            match=failure_message,
        ):
            QueueIamSchema().load(iam_dict)
    else:
        iam = HeadNodeIamSchema().load(iam_dict)
        assert_that(iam.instance_role).is_equal_to(instance_role)
        assert_that(iam.instance_profile).is_equal_to(instance_profile)
        iam = QueueIamSchema().load(iam_dict)
        assert_that(iam.instance_role).is_equal_to(instance_role)
        assert_that(iam.instance_profile).is_equal_to(instance_profile)


@pytest.mark.parametrize(
    "config_dict, failure_message",
    [
        # failures
        ({"KmsKeyId": "test"}, "Unknown field"),
        # success
        (
            {
                "VolumeType": "gp3",
                "Iops": 100,
                "Size": 50,
                "Throughput": 300,
                "Encrypted": True,
                "DeleteOnTermination": True,
            },
            None,
        ),
    ],
)
def test_head_node_root_volume_schema(mocker, config_dict, failure_message):
    mock_aws_api(mocker)

    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            HeadNodeRootVolumeSchema().load(config_dict)
    else:
        HeadNodeRootVolumeSchema().load(config_dict)


DUMMY_AWSBATCH_QUEUE = {
    "Name": "queue1",
    "Networking": {"SubnetIds": ["subnet-12345678"]},
    "ComputeResources": [{"Name": "compute_resource1", "InstanceTypes": ["c5.xlarge"]}],
}


@pytest.mark.parametrize(
    "config_dict, failure_message",
    [
        # Failures
        ({"OnNodeUpdating": "test"}, "Unknown field"),
        (
            {"OnNodeStart": "test", "OnNodeConfigured": "test", "OnNodeUpdated": "test"},
            "Either Script or Sequence field must be provided.",
        ),
        (
            {"OnNodeConfigured": {"Script": "test3", "Args": ["5", "6"], "Sequence": []}},
            "Both Script and Sequence fields are provided. Only one is allowed.",
        ),
        (
            {"OnNodeUpdated": {"ScriptWrong": "test3", "Args": ["5", "6"]}},
            "Either Script or Sequence field must be provided.",
        ),
        (
            {"OnNodeUpdated": {"Sequence": "test"}},
            "Invalid input type for Sequence, expected list.",
        ),
        # Successes
        ({}, None),
        (
            {
                "OnNodeStart": {"Script": "test", "Args": ["1", "2"]},
                "OnNodeConfigured": {"Script": "test2", "Args": ["3", "4"]},
                "OnNodeUpdated": {"Script": "test3", "Args": ["5", "6"]},
            },
            None,
        ),
        (
            {
                "OnNodeStart": {
                    "Sequence": [
                        {"Script": "test1", "Args": ["1", "2"]},
                        {"Script": "test2", "Args": ["1", "2", "3"]},
                        {"Script": "test3"},
                        {"Script": "test4", "Args": []},
                    ]
                },
                "OnNodeConfigured": {"Script": "test2", "Args": ["3", "4"]},
                "OnNodeUpdated": {"Sequence": []},
            },
            None,
        ),
        (
            {
                "OnNodeStart": {"Script": "test"},
                "OnNodeConfigured": {"Script": "test2"},
                "OnNodeUpdated": {"Script": "test3"},
            },
            None,
        ),
        (
            {
                "OnNodeStart": {"Script": "test"},
                "OnNodeConfigured": {"Script": "test2", "Args": ["3", "4"]},
            },
            None,
        ),
    ],
)
def test_head_node_custom_actions_schema(mocker, config_dict, failure_message):
    mock_aws_api(mocker)
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            HeadNodeCustomActionsSchema().load(config_dict)
    else:
        conf = HeadNodeCustomActionsSchema().load(config_dict)
        HeadNodeCustomActionsSchema().dump(conf)


@pytest.mark.parametrize(
    "config_dict, failure_message",
    [
        # Failures
        ({"OnNodeUpdated": "test"}, "Unknown field"),
        (
            {
                "OnNodeStart": "test",
                "OnNodeConfigured": "test",
            },
            "Either Script or Sequence field must be provided.",
        ),
        (
            {"OnNodeStart": {"Script": "test3", "Args": ["5", "6"], "Sequence": []}},
            "Both Script and Sequence fields are provided. Only one is allowed.",
        ),
        ({"OnNodeUpdated": {"Script": "test3", "Args": ["5", "6"]}}, "Unknown field"),
        # Successes
        ({}, None),
        (
            {
                "OnNodeStart": {"Script": "test", "Args": ["1", "2"]},
                "OnNodeConfigured": {"Script": "test2", "Args": ["3", "4"]},
            },
            None,
        ),
        (
            {
                "OnNodeStart": {"Script": "test"},
                "OnNodeConfigured": {"Script": "test2"},
            },
            None,
        ),
        (
            {
                "OnNodeStart": {"Script": "test"},
                "OnNodeConfigured": {"Script": "test2", "Args": ["3", "4"]},
            },
            None,
        ),
        (
            {
                "OnNodeStart": {
                    "Sequence": [
                        {"Script": "test1", "Args": ["1", "2"]},
                        {"Script": "test2", "Args": ["1", "2", "3"]},
                        {"Script": "test3"},
                        {"Script": "test4", "Args": []},
                    ]
                },
                "OnNodeConfigured": {"Sequence": []},
            },
            None,
        ),
        (
            {
                "OnNodeStart": {"Script": "test1", "Args": ["1", "2"]},
                "OnNodeConfigured": {"Sequence": []},
            },
            None,
        ),
    ],
)
def test_queue_custom_actions_schema(mocker, config_dict, failure_message):
    mock_aws_api(mocker)
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            QueueCustomActionsSchema().load(config_dict)
    else:
        conf = QueueCustomActionsSchema().load(config_dict)
        QueueCustomActionsSchema().dump(conf)


def dummy_slurm_queue(name="queue1", number_of_compute_resource=1):
    slurm_queue = {
        "Name": name,
        "Networking": {"SubnetIds": ["subnet-12345678"]},
        "ComputeResources": [],
    }
    for index in range(number_of_compute_resource):
        slurm_queue["ComputeResources"].append(
            dummy_slurm_compute_resource(f"compute_resource{index}", f"c{index}.xlarge")
        )
    return slurm_queue


def dummpy_slurm_queue_list(queue_num):
    return [dummy_slurm_queue(f"queue{index}") for index in range(queue_num)]


def dummy_slurm_compute_resource(name, instance_type):
    return {"Name": name, "InstanceType": instance_type}


@pytest.mark.parametrize(
    "config_dict, failure_message",
    [
        # failures
        ({"Scheduler": "awsbatch"}, "AwsBatchQueues section must be specified"),
        ({"Scheduler": "slurm"}, "SlurmQueues section must be specified"),
        (
            {"Scheduler": "slurm", "AwsBatchQueues": [DUMMY_AWSBATCH_QUEUE]},
            "Queues section is not appropriate to the Scheduler",
        ),
        (
            {"Scheduler": "awsbatch", "SlurmQueues": [dummy_slurm_queue()]},
            "Queues section is not appropriate to the Scheduler",
        ),
        (
            {"Scheduler": "slurm", "SlurmQueues": [dummy_slurm_queue()], "AwsBatchQueues": [DUMMY_AWSBATCH_QUEUE]},
            "Queues section is not appropriate to the Scheduler",
        ),
        (
            {"Scheduler": "slurm", "SlurmSettings": {}, "AwsBatchSettings": {}},
            "Multiple .*Settings sections cannot be specified in the Scheduling section",
        ),
        # success
        ({"Scheduler": "slurm", "SlurmQueues": [dummy_slurm_queue()]}, None),
        (
            {
                "Scheduler": "slurm",
                "SlurmQueues": [
                    dummy_slurm_queue(),
                    {
                        "Name": "queue2",
                        "Networking": {"SubnetIds": ["subnet-12345678"]},
                        "ComputeResources": [
                            {"Name": "compute_resource3", "InstanceType": "c5.2xlarge", "MaxCount": 5},
                            {"Name": "compute_resource4", "InstanceType": "c4.2xlarge"},
                        ],
                    },
                ],
            },
            None,
        ),
        (  # maximum slurm queue length
            {
                "Scheduler": "slurm",
                "SlurmQueues": dummpy_slurm_queue_list(10),
            },
            None,
        ),
        (  # maximum slurm queue length
            {
                "Scheduler": "slurm",
                "SlurmQueues": [dummy_slurm_queue("queue1", number_of_compute_resource=5)],
            },
            None,
        ),
    ],
)
def test_scheduling_schema(mocker, config_dict, failure_message):
    mock_aws_api(mocker)

    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SchedulingSchema().load(config_dict)
    else:
        SchedulingSchema().load(config_dict)


@pytest.mark.parametrize(
    "config_dict, failure_message",
    [
        # Single Instance Type in a Compute Resource
        (
            {
                "Name": "Standard-Queue",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "ComputeResources": [
                    {"Name": "compute_resource1", "InstanceType": "c5.2xlarge", "MaxCount": 5},
                    {"Name": "compute_resource2", "InstanceType": "c4.2xlarge"},
                ],
            },
            "",
        ),
        # Multiple Instance Types in a Compute Resource
        (
            {
                "Name": "Flex-Queue",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "AllocationStrategy": "lowest-price",
                "ComputeResources": [
                    {
                        "Name": "compute_resource1",
                        "Instances": [{"InstanceType": "c5.2xlarge"}],
                    }
                ],
            },
            "",
        ),
        # Mixing Single plus Flexible Instance Type Compute Resources
        (
            {
                "Name": "Flex-Queue",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "AllocationStrategy": "lowest-price",
                "ComputeResources": [
                    {
                        "Name": "compute_resource1",
                        "Instances": [{"InstanceType": "c5.2xlarge"}, {"InstanceType": "c4.2xlarge"}],
                    },
                    {"Name": "compute_resource2", "InstanceType": "c4.2xlarge"},
                ],
            },
            "",
        ),
        # Failing to specify either InstanceType or Instances should return a validation error
        (
            {
                "Name": "Flex-Queue",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "AllocationStrategy": "lowest-price",
                "ComputeResources": [
                    {
                        "Name": "compute_resource1",
                    }
                ],
            },
            "A Compute Resource needs to specify either InstanceType or Instances.",
        ),
        # Mixing InstanceType and Instances in a Compute Resource should return a validation error
        (
            {
                "Name": "Mixed-Instance-Types",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "AllocationStrategy": "lowest-price",
                "ComputeResources": [
                    {
                        "Name": "compute_resource1",
                        "InstanceType": "c5.2xlarge",
                        "Instances": [{"InstanceType": "c4.2xlarge"}],
                    },
                ],
            },
            "A Compute Resource needs to specify either InstanceType or Instances.",
        ),
        # Instances in a Compute Resource should not have duplicate instance types
        (
            {
                "Name": "DuplicateInstanceTypes",
                "ComputeResources": [
                    {
                        "Name": "compute_resource1",
                        "Instances": [
                            {"InstanceType": "c4.2xlarge"},
                            {"InstanceType": "c5.xlarge"},
                            {"InstanceType": "c5a.xlarge"},
                            {"InstanceType": "c4.2xlarge"},
                        ],
                    },
                ],
            },
            "Duplicate instance type \\(c4.2xlarge\\) detected.",
        ),
    ],
)
def test_slurm_flexible_queue(mocker, config_dict, failure_message):
    mock_aws_api(mocker)

    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SlurmQueueSchema().load(config_dict)
    else:
        SlurmQueueSchema().load(config_dict)


@pytest.mark.parametrize(
    "config_dict, failure_message",
    [
        # failures
        ({"StorageType": "Ebs"}, "Missing data for required field."),
        ({"StorageType": "Ebs", "MountDir": "mount/tmp"}, "Missing data for required field."),
        ({"StorageType": "Ebs", "Name": "name"}, "Missing data for required field."),
        ({"StorageType": "Efs", "Name": "name"}, "Missing data for required field."),
        (
            {
                "StorageType": "Ebs",
                "Name": "name",
                "MountDir": "mount/tmp",
                "FsxLustreSettings": {"CopyTagsToBackups": True},
            },
            "SharedStorage > .*Settings section is not appropriate to the",
        ),
        (
            {"StorageType": "Efs", "Name": "name", "MountDir": "mount/tmp", "EbsSettings": {"Encrypted": True}},
            "SharedStorage > .*Settings section is not appropriate to the",
        ),
        (
            {"StorageType": "FsxLustre", "Name": "name", "MountDir": "mount/tmp", "EfsSettings": {"Encrypted": True}},
            "SharedStorage > .*Settings section is not appropriate to the",
        ),
        (
            {
                "StorageType": "Efs",
                "Name": "name",
                "MountDir": "mount/tmp",
                "EbsSettings": {"Encrypted": True},
                "EfsSettings": {"Encrypted": True},
            },
            "Multiple .*Settings sections cannot be specified in the SharedStorage items",
        ),
        (
            {
                "StorageType": "FsxFileCache",
                "Name": "name",
                "MountDir": "mount/tmp",
                "FsxFileCacheSettings": {"FileCacheId": "fc-123456789012345678"},
                "EfsSettings": {"Encrypted": True},
            },
            "Multiple .*Settings sections cannot be specified in the SharedStorage items",
        ),
        # File cache is missing FileCacheSettings/FileCacheId
        ({"StorageType": "FsxFileCache", "MountDir": "mount/tmp"}, "Missing data for required field."),
        # File cache is has unknown Field 'Encrypted'
        (
            {
                "StorageType": "FsxFileCache",
                "Name": "name",
                "MountDir": "mount/tmp",
                "FsxFileCacheSettings": {"Encrypted": True},
            },
            "Unknown field.",
        ),
        # File Cache is missing MountDir field
        (
            {
                "StorageType": "FsxFileCache",
                "Name": "name",
                "FsxFileCacheSettings": {"FileCacheId": "fc-12345678"},
            },
            "Missing data for required field.",
        ),
        # FileCacheID string is less than 11 characters
        (
            {
                "StorageType": "FsxFileCache",
                "Name": "name",
                "MountDir": "mount/tmp",
                "FsxFileCacheSettings": {"FileCacheId": "fc-1234567"},
            },
            "String does not match expected pattern.",
        ),
        # FileCacheID string is greater than 21 characters
        (
            {
                "StorageType": "FsxFileCache",
                "Name": "name",
                "MountDir": "mount/tmp",
                "FsxFileCacheSettings": {"FileCacheId": "fc-1234567890123456789"},
            },
            "String does not match expected pattern.",
        ),
        # success
        (
            {
                "StorageType": "FsxLustre",
                "Name": "name",
                "MountDir": "mount/tmp",
                "FsxLustreSettings": {"CopyTagsToBackups": True},
            },
            None,
        ),
        ({"StorageType": "Efs", "Name": "name", "MountDir": "mount/tmp", "EfsSettings": {"Encrypted": True}}, None),
        ({"StorageType": "Ebs", "Name": "name", "MountDir": "mount/tmp", "EbsSettings": {"Encrypted": True}}, None),
        (
            {
                "StorageType": "FsxFileCache",
                "Name": "name",
                "MountDir": "mount/tmp",
                "FsxFileCacheSettings": {"FileCacheId": "fc-12345678"},
            },
            None,
        ),
        (
            {
                "StorageType": "FsxFileCache",
                "Name": "name",
                "MountDir": "mount/tmp",
                "FsxFileCacheSettings": {"FileCacheId": "fc-123456789012345678"},
            },
            None,
        ),
    ],
)
def test_shared_storage_schema(mocker, config_dict, failure_message):
    mock_aws_api(mocker)

    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SharedStorageSchema().load(config_dict)
    else:
        SharedStorageSchema().load(config_dict)


@pytest.mark.parametrize(
    "scheduler, install_intel_packages_enabled, failure_message",
    [
        ("slurm", True, None),
        ("slurm", False, None),
        ("awsbatch", True, "use of the IntelSoftware configuration is not supported when using awsbatch"),
        ("awsbatch", False, None),
    ],
)
def test_scheduler_constraints_for_intel_packages(
    mocker, test_datadir, scheduler, install_intel_packages_enabled, failure_message
):
    mock_aws_api(mocker)
    config_file_name = f"{scheduler}.{'enabled' if install_intel_packages_enabled else 'disabled'}.yaml"
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            load_cluster_model_from_yaml(config_file_name, test_datadir)
    else:
        _, cluster = load_cluster_model_from_yaml(config_file_name, test_datadir)
        assert_that(cluster.scheduling.scheduler).is_equal_to(scheduler)
        assert_that(cluster.additional_packages.intel_software.intel_hpc_platform).is_equal_to(
            install_intel_packages_enabled
        )


@pytest.mark.parametrize(
    "scheduler, custom_action, failure_message",
    [
        ("slurm", "no_actions", None),
        ("slurm", "on_node_start", None),
        ("slurm", "on_node_configured", None),
        ("slurm", "on_node_updated", None),
        ("awsbatch", "no_actions", None),
        ("awsbatch", "on_node_start", None),
        ("awsbatch", "on_node_configured", None),
        (
            "awsbatch",
            "on_node_updated",
            "The use of the OnNodeUpdated configuration is not supported when using awsbatch as the scheduler",
        ),
    ],
)
def test_scheduler_constraints_for_custom_actions(mocker, test_datadir, scheduler, custom_action, failure_message):
    mock_aws_api(mocker)
    config_file_name = f"{scheduler}.{custom_action}.yaml"
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            load_cluster_model_from_yaml(config_file_name, test_datadir)
    else:
        _, cluster = load_cluster_model_from_yaml(config_file_name, test_datadir)
        assert_that(cluster.scheduling.scheduler).is_equal_to(scheduler)


@pytest.mark.parametrize(
    "head_node_bootstrap_timeout, compute_node_bootstrap_timeout, failure_message",
    [
        (1800, None, None),
        (1200, 1000, None),
        (-1, None, "Must be greater than or equal to 1."),
        (None, -1, "Must be greater than or equal to 1."),
        (None, None, None),
    ],
)
def test_timeouts_schema(head_node_bootstrap_timeout, compute_node_bootstrap_timeout, failure_message):
    timeouts_schema = {}
    if head_node_bootstrap_timeout:
        timeouts_schema["HeadNodeBootstrapTimeout"] = head_node_bootstrap_timeout
    if compute_node_bootstrap_timeout:
        timeouts_schema["ComputeNodeBootstrapTimeout"] = compute_node_bootstrap_timeout

    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            TimeoutsSchema().load(timeouts_schema)
    else:
        timeouts = TimeoutsSchema().load(timeouts_schema)
        assert_that(timeouts.head_node_bootstrap_timeout).is_equal_to(
            head_node_bootstrap_timeout or NODE_BOOTSTRAP_TIMEOUT
        )
        assert_that(timeouts.compute_node_bootstrap_timeout).is_equal_to(
            compute_node_bootstrap_timeout or NODE_BOOTSTRAP_TIMEOUT
        )


@pytest.mark.parametrize(
    "config_dict, failure_message, expected_queue_gpu_hc, expected_cr1_gpu_hc, expected_cr2_gpu_hc",
    [
        # HealthChecks dictionary is empty
        (
            {
                "Name": "Standard-Queue",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "ComputeResources": [
                    {"Name": "compute_resource1", "InstanceType": "c5.2xlarge", "MaxCount": 5},
                    {"Name": "compute_resource2", "InstanceType": "c4.2xlarge"},
                ],
                "HealthChecks": {},
            },
            "",
            None,
            None,
            None,
        ),
        # Health Checks sections are not defined
        (
            {
                "Name": "Standard-Queue",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "ComputeResources": [
                    {"Name": "compute_resource1", "InstanceType": "c5.2xlarge", "MaxCount": 5},
                    {"Name": "compute_resource2", "InstanceType": "c4.2xlarge"},
                ],
            },
            "",
            None,
            None,
            None,
        ),
        # Health Checks section is defined at queue level
        (
            {
                "Name": "Standard-Queue",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "ComputeResources": [
                    {"Name": "compute_resource1", "InstanceType": "c5.2xlarge", "MaxCount": 5},
                    {"Name": "compute_resource2", "InstanceType": "c4.2xlarge"},
                ],
                "HealthChecks": {"Gpu": {"Enabled": True}},
            },
            "",
            True,
            None,
            None,
        ),
        # Health Checks section is defined in a single compute resource
        (
            {
                "Name": "Standard-Queue",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "ComputeResources": [
                    {"Name": "compute_resource1", "InstanceType": "c5.2xlarge", "MaxCount": 5},
                    {
                        "Name": "compute_resource2",
                        "InstanceType": "c4.2xlarge",
                        "HealthChecks": {"Gpu": {"Enabled": True}},
                    },
                ],
            },
            "",
            None,
            None,
            True,
        ),
        # Health Checks sections are defined at queue level and a single compute resource
        (
            {
                "Name": "Standard-Queue",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "ComputeResources": [
                    {"Name": "compute_resource1", "InstanceType": "c5.2xlarge", "MaxCount": 5},
                    {
                        "Name": "compute_resource2",
                        "InstanceType": "c4.2xlarge",
                        "HealthChecks": {"Gpu": {"Enabled": True}},
                    },
                ],
                "HealthChecks": {"Gpu": {"Enabled": True}},
            },
            "",
            True,
            None,
            True,
        ),
        # Health Checks sections are defined at queue level and in both compute resource
        (
            {
                "Name": "Standard-Queue",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "ComputeResources": [
                    {
                        "Name": "compute_resource1",
                        "InstanceType": "c5.2xlarge",
                        "MaxCount": 5,
                        "HealthChecks": {"Gpu": {"Enabled": True}},
                    },
                    {
                        "Name": "compute_resource2",
                        "InstanceType": "c4.2xlarge",
                        "HealthChecks": {"Gpu": {"Enabled": True}},
                    },
                ],
                "HealthChecks": {"Gpu": {"Enabled": True}},
            },
            "",
            True,
            True,
            True,
        ),
        # Gpu Health Check enable is defined using the true string value instead of the boolean value
        (
            {
                "Name": "Standard-Queue",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "ComputeResources": [
                    {"Name": "compute_resource1", "InstanceType": "c5.2xlarge", "MaxCount": 5},
                    {"Name": "compute_resource2", "InstanceType": "c4.2xlarge"},
                ],
                "HealthChecks": {"Gpu": {"Enabled": "true"}},
            },
            "",
            True,
            None,
            None,
        ),
        # Gpu Health Check enable is defined using the true integer value instead of the boolean value
        (
            {
                "Name": "Standard-Queue",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "ComputeResources": [
                    {"Name": "compute_resource1", "InstanceType": "c5.2xlarge", "MaxCount": 5},
                    {"Name": "compute_resource2", "InstanceType": "c4.2xlarge"},
                ],
                "HealthChecks": {"Gpu": {"Enabled": 1}},
            },
            "",
            True,
            None,
            None,
        ),
        # Gpu Health Check enable is defined using a string, and it doesn't represent a boolean
        (
            {
                "Name": "Standard-Queue",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "ComputeResources": [
                    {"Name": "compute_resource1", "InstanceType": "c5.2xlarge", "MaxCount": 5},
                    {"Name": "compute_resource2", "InstanceType": "c4.2xlarge"},
                ],
                "HealthChecks": {"Gpu": {"Enabled": "vero"}},
            },
            "Not a valid boolean",
            None,
            None,
            None,
        ),
        # Gpu Health Check enable is defined using an integer, and it doesn't represent a boolean
        (
            {
                "Name": "Standard-Queue",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "ComputeResources": [
                    {"Name": "compute_resource1", "InstanceType": "c5.2xlarge", "MaxCount": 5},
                    {"Name": "compute_resource2", "InstanceType": "c4.2xlarge"},
                ],
                "HealthChecks": {"Gpu": {"Enabled": -1}},
            },
            "Not a valid boolean",
            None,
            None,
            None,
        ),
        # Gpu Health Check enable is not defined
        (
            {
                "Name": "Standard-Queue",
                "Networking": {"SubnetIds": ["subnet-12345678"]},
                "ComputeResources": [
                    {"Name": "compute_resource1", "InstanceType": "c5.2xlarge", "MaxCount": 5},
                    {"Name": "compute_resource2", "InstanceType": "c4.2xlarge"},
                ],
                "HealthChecks": {"Gpu"},
            },
            "Invalid input type",
            None,
            None,
            None,
        ),
    ],
)
def test_slurm_gpu_health_checks(
    mocker,
    config_dict,
    failure_message,
    expected_queue_gpu_hc,
    expected_cr1_gpu_hc,
    expected_cr2_gpu_hc,
):
    mock_aws_api(mocker)
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SlurmQueueSchema().load(config_dict)
    else:
        queue = SlurmQueueSchema().load(config_dict)
        assert_that(queue.health_checks.gpu.enabled).is_equal_to(expected_queue_gpu_hc)
        assert_that(queue.compute_resources[0].health_checks.gpu.enabled).is_equal_to(expected_cr1_gpu_hc)
        assert_that(queue.compute_resources[1].health_checks.gpu.enabled).is_equal_to(expected_cr2_gpu_hc)


@pytest.mark.parametrize(
    "config_dict, failure_message",
    [
        # Failures
        ({"Keys": "my_key", "Value": "my_value"}, "Unknown field"),
        ({"Key": "my_key"}, "Missing data for required field"),
        ({"Value": "my_value"}, "Missing data for required field"),
        (
            {
                "Key": "my_test",
                "Value": "my_value",
            },
            None,
        ),
    ],
)
def test_queue_tag_schema(mocker, config_dict, failure_message):
    mock_aws_api(mocker)
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            QueueTagSchema().load(config_dict)
    else:
        conf = QueueTagSchema().load(config_dict)
        QueueTagSchema().dump(conf)
