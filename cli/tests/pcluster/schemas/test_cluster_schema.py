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


def _check_cluster_schema(test_datadir, config_file_name):
    # https://github.com/marshmallow-code/marshmallow/issues/1126
    # TODO use yaml render_module: https://marshmallow.readthedocs.io/en/3.0/api_reference.html#marshmallow.Schema.Meta

    # Load cluster model from Yaml file
    input_yaml = load_yaml_dict(test_datadir / config_file_name)
    print(input_yaml)
    copy_input_yaml = deepcopy(input_yaml)
    cluster = ClusterSchema(cluster_name="clustername").load(copy_input_yaml)
    print(cluster)

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
    "instance_role, instance_profile, additional_iam_policies, failure_message",
    [
        (None, None, "arn:aws:iam::aws:policy/AdministratorAccess", False),
        ("arn:aws:iam::aws:role/CustomHeadNodeRole", None, "arn:aws:iam::aws:policy/AdministratorAccess", True),
        (
            "arn:aws:iam::aws:role/CustomHeadNodeRole",
            "arn:aws:iam::aws:instance-profile/CustomNodeInstanceProfile",
            None,
            True,
        ),
        (None, "arn:aws:iam::aws:instance-profile/CustomNodeInstanceProfile", None, False),
        ("arn:aws:iam::aws:role/CustomHeadNodeRole", None, None, False),
    ],
)
def test_iam_schema(instance_role, instance_profile, additional_iam_policies, failure_message):
    iam_dict = dict()
    if instance_role:
        iam_dict["InstanceRole"] = instance_role
    if instance_profile:
        iam_dict["InstanceProfile"] = instance_profile
    if additional_iam_policies:
        iam_dict["AdditionalIamPolicies"] = [{"Policy": additional_iam_policies}]

    if failure_message:
        with pytest.raises(
            ValidationError,
            match="InstanceProfile, InstanceRole or AdditionalIamPolicies can not be configured together.",
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

DUMMY_SLURM_QUEUE = {
    "Name": "queue1",
    "Networking": {"SubnetIds": ["subnet-12345678"]},
    "ComputeResources": [{"Name": "compute_resource1", "InstanceType": "c5.xlarge"}],
}


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
            {"Scheduler": "awsbatch", "SlurmQueues": [DUMMY_SLURM_QUEUE]},
            "Queues section is not appropriate to the Scheduler",
        ),
        (
            {"Scheduler": "slurm", "SlurmQueues": [DUMMY_SLURM_QUEUE], "AwsBatchQueues": [DUMMY_AWSBATCH_QUEUE]},
            "Queues section is not appropriate to the Scheduler",
        ),
        (
            {"Scheduler": "slurm", "SlurmSettings": {}, "AwsBatchSettings": {}},
            "Multiple .*Settings sections cannot be specified in the Scheduling section",
        ),
        # success
        ({"Scheduler": "slurm", "SlurmQueues": [DUMMY_SLURM_QUEUE]}, None),
        (
            {
                "Scheduler": "slurm",
                "SlurmQueues": [
                    DUMMY_SLURM_QUEUE,
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
                    DUMMY_SLURM_QUEUE,
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
            "SubnetIds configured in different queues should be the same",
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
