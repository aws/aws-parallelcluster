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
from io import BytesIO
from urllib.error import HTTPError

import pytest
import yaml
from assertpy import assert_that
from botocore.response import StreamingBody
from marshmallow.validate import ValidationError
from yaml.parser import ParserError

from pcluster.aws.common import AWSClientError
from pcluster.constants import NODE_BOOTSTRAP_TIMEOUT, SUPPORTED_OSES
from pcluster.schemas.cluster_schema import (
    ClusterSchema,
    HeadNodeCustomActionsSchema,
    HeadNodeIamSchema,
    HeadNodeRootVolumeSchema,
    ImageSchema,
    QueueCustomActionsSchema,
    QueueIamSchema,
    SchedulerPluginCloudFormationClusterInfrastructureSchema,
    SchedulerPluginClusterSharedArtifactSchema,
    SchedulerPluginDefinitionSchema,
    SchedulerPluginFileSchema,
    SchedulerPluginLogsSchema,
    SchedulerPluginResourcesSchema,
    SchedulerPluginSettingsSchema,
    SchedulerPluginSupportedDistrosSchema,
    SchedulerPluginUserSchema,
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


@pytest.mark.parametrize("config_file_name", ["scheduler_plugin.required.yaml", "scheduler_plugin.full.yaml"])
def test_cluster_schema_scheduler_plugin(mocker, test_datadir, config_file_name):
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
        ({"OnNodeStart": "test", "OnNodeConfigured": "test", "OnNodeUpdated": "test"}, "Invalid input type."),
        ({"OnNodeUpdated": {"ScriptWrong": "test3", "Args": ["5", "6"]}}, "Unknown field"),
        # Successes
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
        HeadNodeCustomActionsSchema().load(config_dict)


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
            "Invalid input type.",
        ),
        ({"OnNodeUpdated": {"Script": "test3", "Args": ["5", "6"]}}, "Unknown field"),
        # Successes
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
    ],
)
def test_queue_custom_actions_schema(mocker, config_dict, failure_message):
    mock_aws_api(mocker)
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            QueueCustomActionsSchema().load(config_dict)
    else:
        QueueCustomActionsSchema().load(config_dict)


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
    "x86, arm64, failure_message",
    [
        (None, ["centos7"], None),
        (["centos7"], None, None),
        ("ubuntu1804", ["centos7"], "Not a valid list"),
        (["ubuntu1804"], ["centos7"], None),
    ],
)
def test_scheduler_plugin_supported_distros_schema(x86, arm64, failure_message):
    scheduler_plugin_supported_distros_schema = {}
    if x86:
        scheduler_plugin_supported_distros_schema["X86"] = x86
    if arm64:
        scheduler_plugin_supported_distros_schema["Arm64"] = arm64

    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SchedulerPluginSupportedDistrosSchema().load(scheduler_plugin_supported_distros_schema)
    else:
        scheduler_plugin_supported_distros = SchedulerPluginSupportedDistrosSchema().load(
            scheduler_plugin_supported_distros_schema
        )
        assert_that(scheduler_plugin_supported_distros.x86).is_equal_to(x86 or SUPPORTED_OSES)
        assert_that(scheduler_plugin_supported_distros.arm64).is_equal_to(arm64 or SUPPORTED_OSES)


@pytest.mark.parametrize(
    "template, failure_message",
    [
        ("https://template.yaml", None),
        (None, "Missing data for required field."),
    ],
)
def test_cloudformation_cluster_infrastructure_schema(mocker, template, failure_message):
    scheduler_plugin_cloudformation_cluster_infrastructure_schema = {}
    mocker.patch("pcluster.utils.get_region", return_value="fake_region")
    mocker.patch("pcluster.utils.replace_url_parameters", return_value="fake_url")
    if template:
        scheduler_plugin_cloudformation_cluster_infrastructure_schema["Template"] = template

    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SchedulerPluginCloudFormationClusterInfrastructureSchema().load(
                scheduler_plugin_cloudformation_cluster_infrastructure_schema
            )
    else:
        scheduler_plugin_cloudformation_cluster_infrastructure = (
            SchedulerPluginCloudFormationClusterInfrastructureSchema().load(
                scheduler_plugin_cloudformation_cluster_infrastructure_schema
            )
        )
        assert_that(scheduler_plugin_cloudformation_cluster_infrastructure.template).is_equal_to(template)


@pytest.mark.parametrize(
    "source, failure_message",
    [
        ("https://artifacts.gz", None),
        (None, "Missing data for required field."),
    ],
)
def test_scheduler_plugin_cluster_shared_artifact_schema(mocker, source, failure_message):
    scheduler_plugin_cluster_shared_artifact_schema = {}
    mocker.patch("pcluster.utils.get_region", return_value="fake_region")
    mocker.patch("pcluster.utils.replace_url_parameters", return_value="fake_url")
    if source:
        scheduler_plugin_cluster_shared_artifact_schema["Source"] = source

    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SchedulerPluginClusterSharedArtifactSchema().load(scheduler_plugin_cluster_shared_artifact_schema)
    else:
        scheduler_plugin_cluster_shared_artifact = SchedulerPluginClusterSharedArtifactSchema().load(
            scheduler_plugin_cluster_shared_artifact_schema
        )
        assert_that(scheduler_plugin_cluster_shared_artifact.source).is_equal_to(source)


@pytest.mark.parametrize(
    "artifacts, failure_message",
    [
        (["https://artifacts.gz"], None),
        (["https://artifacts1.gz", "https://artifacts2.gz"], None),
        (None, "Missing data for required field."),
    ],
)
def test_scheduler_plugin_resources_schema(mocker, artifacts, failure_message):
    scheduler_plugin_resources_schema = {}
    mocker.patch("pcluster.utils.get_region", return_value="fake_region")
    mocker.patch("pcluster.utils.replace_url_parameters", return_value="fake_url")
    if artifacts:
        scheduler_plugin_resources_schema["ClusterSharedArtifacts"] = [{"Source": item} for item in artifacts]
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SchedulerPluginResourcesSchema().load(scheduler_plugin_resources_schema)
    else:
        scheduler_plugin_resources = SchedulerPluginResourcesSchema().load(scheduler_plugin_resources_schema)
        for artifact, source in zip(scheduler_plugin_resources.cluster_shared_artifacts, artifacts):
            assert_that(artifact.source).is_equal_to(source)


@pytest.mark.parametrize(
    "name, enable_imds, failure_message",
    [
        ("user1", True, None),
        ("user1", None, None),
        (None, True, "Missing data for required field."),
    ],
)
def test_scheduler_plugin_user_schema(name, enable_imds, failure_message):
    scheduler_plugin_user_schema = {}
    if name:
        scheduler_plugin_user_schema["Name"] = name
    if enable_imds:
        scheduler_plugin_user_schema["EnableImds"] = enable_imds
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SchedulerPluginUserSchema().load(scheduler_plugin_user_schema)
    else:
        scheduler_plugin_user = SchedulerPluginUserSchema().load(scheduler_plugin_user_schema)
        assert_that(scheduler_plugin_user.name).is_equal_to(name)
        if enable_imds:
            assert_that(scheduler_plugin_user.enable_imds).is_equal_to(enable_imds)
        else:
            assert_that(scheduler_plugin_user.enable_imds).is_equal_to(False)


@pytest.mark.parametrize(
    "file_path, timestamp_format, log_stream_name, failure_message",
    [
        ("/var/log/slurmctld.log", None, "slurmctld.log", None),
        ("/var/log/slurmctld.log", "%Y-%m-%d %H:%M:%S,%f", "slurmctld.log", None),
        (
            None,
            "%Y-%m-%d %H:%M:%S,%f",
            "slurmctld.log",
            "Missing data for required field.",
        ),
        (
            "/var/log/slurmctld.log",
            "%Y-%m-%d %H:%M:%S,%f",
            None,
            "Missing data for required field.",
        ),
    ],
)
def test_scheduler_plugin_file_schema(file_path, timestamp_format, failure_message, log_stream_name):
    scheduler_plugin_file_schema = {}
    if file_path:
        scheduler_plugin_file_schema["FilePath"] = file_path
    if timestamp_format:
        scheduler_plugin_file_schema["TimestampFormat"] = timestamp_format
    if log_stream_name:
        scheduler_plugin_file_schema["LogStreamName"] = log_stream_name
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SchedulerPluginFileSchema().load(scheduler_plugin_file_schema)
    else:
        scheduler_plugin_file = SchedulerPluginFileSchema().load(scheduler_plugin_file_schema)
        assert_that(scheduler_plugin_file.file_path).is_equal_to(file_path)
        if timestamp_format:
            assert_that(scheduler_plugin_file.timestamp_format).is_equal_to(timestamp_format)
        else:
            assert_that(scheduler_plugin_file.timestamp_format).is_equal_to("%Y-%m-%dT%H:%M:%S%z")


@pytest.mark.parametrize(
    "files, failure_message",
    [
        (
            [{"FilePath": "/var/log/slurmctld.log", "TimestampFormat": "%Y-%m-%d %H:%M:%S,%f", "LogStreamName": "log"}],
            None,
        ),
        (
            [
                {
                    "FilePath": "/var/log/slurmctld.log",
                    "TimestampFormat": "%Y-%m-%d %H:%M:%S,%f",
                    "LogStreamName": "log1",
                },
                {"FilePath": "/var/log/scaling.log", "TimestampFormat": "", "LogStreamName": "log2"},
            ],
            None,
        ),
        (None, "Missing data for required field."),
    ],
)
def test_scheduler_plugin_logs_schema(files, failure_message):
    scheduler_plugin_logs_schema = {}
    if files:
        scheduler_plugin_logs_schema["Files"] = files
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SchedulerPluginLogsSchema().load(scheduler_plugin_logs_schema)
    else:
        scheduler_plugin_logs = SchedulerPluginLogsSchema().load(scheduler_plugin_logs_schema)
        for file, expected_file in zip(scheduler_plugin_logs.files, files):
            assert_that(file.file_path).is_equal_to(expected_file["FilePath"])
            assert_that(file.timestamp_format).is_equal_to(expected_file["TimestampFormat"])


@pytest.mark.parametrize(
    "plugin_interface_version, events, failure_message",
    [
        ("1.0", {"HeadInit": {"ExecuteCommand": {"Command": "env"}}}, None),
        (None, {"HeadInit": {"ExecuteCommand": {"Command": "env"}}}, "Missing data for required field."),
        ("1.0", None, "Missing data for required field."),
        ("1.2.0", {"HeadInit": {"ExecuteCommand": {"Command": "env"}}}, "String does not match expected pattern."),
        ("1", {"HeadInit": {"ExecuteCommand": {"Command": "env"}}}, "String does not match expected pattern."),
        ("1.", {"HeadInit": {"ExecuteCommand": {"Command": "env"}}}, "String does not match expected pattern."),
        (".1", {"HeadInit": {"ExecuteCommand": {"Command": "env"}}}, "String does not match expected pattern."),
    ],
)
def test_scheduler_plugin_scheduler_definition_schema(plugin_interface_version, events, failure_message):
    scheduler_plugin_definition_schema = {"Metadata": {"Name": "name", "Version": "1.0"}}
    if plugin_interface_version:
        scheduler_plugin_definition_schema["PluginInterfaceVersion"] = plugin_interface_version
    if events:
        scheduler_plugin_definition_schema["Events"] = events
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SchedulerPluginDefinitionSchema().load(scheduler_plugin_definition_schema)
    else:
        scheduler_plugin_definition = SchedulerPluginDefinitionSchema().load(scheduler_plugin_definition_schema)
        assert_that(scheduler_plugin_definition.plugin_interface_version).is_equal_to(plugin_interface_version)
        assert_that(scheduler_plugin_definition.events.head_init.execute_command.command).is_equal_to(
            events["HeadInit"]["ExecuteCommand"]["Command"]
        )


@pytest.mark.parametrize(
    "scheduler_definition, grant_sudo_privileges, scheduler_definition_s3_bucket_owner, scheduler_definition_checksum, "
    "s3_error, https_error, yaml_load_error, failure_message",
    [
        ("s3://bucket/scheduler_definition.yaml", True, None, None, None, None, None, None),
        (
            "s3://bucket/scheduler_definition_fake.yaml",
            True,
            None,
            None,
            AWSClientError(function_name="get_object", message="The specified key does not exist."),
            None,
            None,
            "Error while downloading scheduler definition from "
            "s3://bucket/scheduler_definition_fake.yaml: The specified key does not exist.",
        ),
        (
            "https://bucket.s3.us-east-2.amazonaws.com/scheduler_definition.yaml",
            False,
            None,
            None,
            None,
            None,
            None,
            None,
        ),
        (
            "https://bucket.s3.us-east-2.amazonaws.com/scheduler_definition_fake.yaml",
            None,
            None,
            None,
            None,
            HTTPError(
                url="https://test-slurm.s3.us-east-2.amazonaws.com/scheduler_definition_fake.yaml",
                code=403,
                msg="Forbidden",
                hdrs="dummy",
                fp="dummy",
            ),
            None,
            "Error while downloading scheduler definition from "
            "https://bucket.s3.us-east-2.amazonaws.com/scheduler_definition_fake.yaml: "
            "The provided URL is invalid or unavailable.",
        ),
        (
            {
                "PluginInterfaceVersion": "1.0",
                "Events": {"HeadInit": {"ExecuteCommand": {"Command": "env"}}},
                "Metadata": {"Name": "name", "Version": "1.0"},
            },
            True,
            None,
            None,
            None,
            None,
            None,
            None,
        ),
        (
            "ftp://bucket/scheduler_definition_fake.yaml",
            True,
            None,
            None,
            None,
            None,
            None,
            r"Error while downloading scheduler definition from ftp://bucket/scheduler_definition_fake.yaml: "
            r"The provided value for SchedulerDefinition is invalid. "
            r"You can specify this as an S3 URL, HTTPS URL or as an inline YAML object.",
        ),
        (
            "s3://bucket/scheduler_definition.yaml",
            True,
            None,
            None,
            None,
            None,
            ParserError("parse error"),
            r"The retrieved SchedulerDefinition \(s3://bucket/scheduler_definition.yaml\) is not a valid YAML.",
        ),
        (
            "https://bucket.s3.us-east-2.amazonaws.com/scheduler_definition_fake.yaml",
            True,
            "01234567890",
            "123467",
            None,
            None,
            None,
            r"SchedulerDefinitionS3BucketOwner can only be specified when SchedulerDefinition is S3 URL",
        ),
        (
            {
                "PluginInterfaceVersion": "1.0",
                "Events": {"HeadInit": {"ExecuteCommand": {"Command": "env"}}},
                "Metadata": {"Name": "name", "Version": "1.0"},
            },
            True,
            "01234567890",
            "123467",
            None,
            None,
            None,
            r"SchedulerDefinitionS3BucketOwner or SchedulerDefinitionChecksum can only specified when "
            "SchedulerDefinition is a URL.",
        ),
        (
            "s3://bucket/scheduler_definition.yaml",
            True,
            "012345678910",
            "aaf9ef48183302fd893d6f6004859289fd9eef095980ef208c1725054ff466da",
            # this checksum can be generated by hashlib.sha256(file_content.encode()).hexdigest()
            # For example, in the test, the file content of scheduler definition is:
            # '{"PluginInterfaceVersion": "1.0", "Events": {"HeadInit": {"ExecuteCommand": {"Command": "env"}}},
            # "Metadata": {"Name": "name", "Version": "1.0"}}'
            None,
            None,
            None,
            None,
        ),
        (
            "s3://bucket/scheduler_definition.yaml",
            True,
            "01234567890",
            None,
            AWSClientError(function_name="get_object", message="Access Denied", error_code="AccessDenied"),
            None,
            None,
            r"Error while downloading scheduler definition from s3://bucket/scheduler_definition.yaml: Access Denied. "
            "This can be due to bucket owner not matching the expected one '01234567890'",
        ),
        (
            "s3://bucket/scheduler_definition.yaml",
            True,
            "012345678910",
            "7f48cf28d516b51efa5deb9af3c338c29444199811751ddcfbe71366847c1ab1",
            None,
            None,
            None,
            r"Error when validating SchedulerDefinition",
        ),
    ],
)
def test_scheduler_plugin_settings_schema(
    mocker,
    scheduler_definition,
    grant_sudo_privileges,
    scheduler_definition_s3_bucket_owner,
    scheduler_definition_checksum,
    s3_error,
    https_error,
    yaml_load_error,
    failure_message,
):
    scheduler_plugin_settings_schema = {}
    body_encoded = json.dumps(
        {
            "PluginInterfaceVersion": "1.0",
            "Events": {"HeadInit": {"ExecuteCommand": {"Command": "env"}}},
            "Metadata": {"Name": "name", "Version": "1.0"},
        }
    ).encode("utf8")
    if isinstance(scheduler_definition, str):
        if scheduler_definition.startswith("s3"):
            mocker.patch(
                "pcluster.aws.s3.S3Client.get_object",
                return_value={"Body": StreamingBody(BytesIO(body_encoded), len(body_encoded))},
                side_effect=s3_error,
            )
        else:
            file_mock = mocker.MagicMock()
            file_mock.read.return_value.decode.return_value = body_encoded
            mocker.patch(
                "pcluster.schemas.cluster_schema.urlopen", side_effect=https_error
            ).return_value.__enter__.return_value = file_mock
    if yaml_load_error:
        mocker.patch("pcluster.utils.yaml.safe_load", side_effect=yaml_load_error)
    if scheduler_definition:
        scheduler_plugin_settings_schema["SchedulerDefinition"] = scheduler_definition
    if grant_sudo_privileges:
        scheduler_plugin_settings_schema["GrantSudoPrivileges"] = grant_sudo_privileges
    if scheduler_definition_s3_bucket_owner:
        scheduler_plugin_settings_schema["SchedulerDefinitionS3BucketOwner"] = scheduler_definition_s3_bucket_owner
    if scheduler_definition_checksum:
        scheduler_plugin_settings_schema["SchedulerDefinitionChecksum"] = scheduler_definition_checksum
    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SchedulerPluginSettingsSchema().load(scheduler_plugin_settings_schema)
    else:
        scheduler_plugin_settings = SchedulerPluginSettingsSchema().load(scheduler_plugin_settings_schema)
        assert_that(scheduler_plugin_settings.scheduler_definition.plugin_interface_version).is_equal_to("1.0")
        assert_that(
            scheduler_plugin_settings.scheduler_definition.events.head_init.execute_command.command
        ).is_equal_to("env")
        if grant_sudo_privileges:
            assert_that(scheduler_plugin_settings.grant_sudo_privileges).is_equal_to(grant_sudo_privileges)
        else:
            assert_that(scheduler_plugin_settings.grant_sudo_privileges).is_equal_to(False)


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
