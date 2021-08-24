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
from copy import deepcopy

import pytest
import yaml
from assertpy import assert_that
from marshmallow.validate import ValidationError

from pcluster.schemas.cluster_schema import ClusterSchema, IamSchema, ImageSchema, SchedulingSchema, SharedStorageSchema
from pcluster.utils import load_yaml_dict
from tests.pcluster.aws.dummy_aws_api import mock_aws_api


def _load_cluster_model_from_yaml(test_datadir, config_file_name):
    # https://github.com/marshmallow-code/marshmallow/issues/1126
    # TODO use yaml render_module: https://marshmallow.readthedocs.io/en/3.0/api_reference.html#marshmallow.Schema.Meta
    input_yaml = load_yaml_dict(test_datadir / config_file_name)
    print(input_yaml)
    copy_input_yaml = deepcopy(input_yaml)
    cluster = ClusterSchema(cluster_name="clustername").load(copy_input_yaml)
    print(cluster)
    return input_yaml, cluster


def _check_cluster_schema(test_datadir, config_file_name):
    # Load cluster model from Yaml file
    input_yaml, cluster = _load_cluster_model_from_yaml(test_datadir, config_file_name)

    # Re-create Yaml file from model and compare content
    cluster_schema = ClusterSchema(cluster_name="clustername")
    cluster_schema.context = {"delete_defaults_when_dump": True}
    output_json = cluster_schema.dump(cluster)
    assert_that(json.dumps(input_yaml, sort_keys=True)).is_equal_to(json.dumps(output_json, sort_keys=True))

    # Print output yaml
    output_yaml = yaml.dump(output_json)
    print(output_yaml)


@pytest.mark.parametrize("config_file_name", ["slurm.required.yaml", "slurm.full.yaml"])
def test_cluster_schema_slurm(mocker, test_datadir, config_file_name):
    mock_aws_api(mocker)
    _check_cluster_schema(test_datadir, config_file_name)


@pytest.mark.parametrize("config_file_name", ["awsbatch.simple.yaml", "awsbatch.full.yaml"])
def test_cluster_schema_awsbatch(test_datadir, config_file_name):
    _check_cluster_schema(test_datadir, config_file_name)


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
            IamSchema().load(iam_dict)
    else:
        iam = IamSchema().load(iam_dict)
        assert_that(iam.instance_role).is_equal_to(instance_role)
        assert_that(iam.instance_profile).is_equal_to(instance_profile)


DUMMY_AWSBATCH_QUEUE = {
    "Name": "queue1",
    "Networking": {"SubnetIds": ["subnet-12345678"]},
    "ComputeResources": [{"Name": "compute_resource1", "InstanceTypes": ["c5.xlarge"]}],
}


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
        (
            {
                "Scheduler": "slurm",
                "SlurmQueues": [
                    dummy_slurm_queue(),
                    {
                        "Name": "queue2",
                        "Networking": {"SubnetIds": ["subnet-00000000"]},
                        "ComputeResources": [
                            {"Name": "compute_resource3", "InstanceType": "c5.2xlarge", "MaxCount": 5},
                            {"Name": "compute_resource4", "InstanceType": "c4.2xlarge"},
                        ],
                    },
                ],
            },
            "The SubnetIds used for all of the queues should be the same",
        ),
        (  # maximum slurm queue length
            {
                "Scheduler": "slurm",
                "SlurmQueues": [
                    dummy_slurm_queue("queue1"),
                    dummy_slurm_queue("queue2"),
                    dummy_slurm_queue("queue3"),
                    dummy_slurm_queue("queue4"),
                    dummy_slurm_queue("queue5"),
                ],
            },
            None,
        ),
        (  # beyond maximum slurm queue length
            {
                "Scheduler": "slurm",
                "SlurmQueues": [
                    dummy_slurm_queue("queue1"),
                    dummy_slurm_queue("queue2"),
                    dummy_slurm_queue("queue3"),
                    dummy_slurm_queue("queue4"),
                    dummy_slurm_queue("queue5"),
                    dummy_slurm_queue("queue6"),
                ],
            },
            "Queue.*Longer than maximum length 5",
        ),
        (  # maximum slurm queue length
            {
                "Scheduler": "slurm",
                "SlurmQueues": [dummy_slurm_queue("queue1", number_of_compute_resource=3)],
            },
            None,
        ),
        (  # beyond maximum slurm queue length
            {
                "Scheduler": "slurm",
                "SlurmQueues": [dummy_slurm_queue("queue1", number_of_compute_resource=4)],
            },
            "ComputeResources.*Longer than maximum length 3",
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
        ("awsbatch", True, "use of the IntelSelectSolutions package is not supported when using awsbatch"),
        ("awsbatch", False, None),
    ],
)
def test_scheduler_constraints_for_intel_packages(
    mocker, test_datadir, scheduler, install_intel_packages_enabled, failure_message
):
    mock_aws_api(mocker)
    config_file_name = f"{scheduler}.{'enabled' if install_intel_packages_enabled else 'disabled'}.yaml"
    if failure_message:
        with pytest.raises(
            ValidationError,
            match=failure_message,
        ):
            _load_cluster_model_from_yaml(test_datadir, config_file_name)
    else:
        _, cluster = _load_cluster_model_from_yaml(test_datadir, config_file_name)
        assert_that(cluster.scheduling.scheduler).is_equal_to(scheduler)
        assert_that(cluster.additional_packages.intel_select_solutions.install_intel_software).is_equal_to(
            install_intel_packages_enabled
        )
