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

from common.utils import load_yaml
from pcluster.config.cluster_config import EbsConfig
from pcluster.schemas.cluster_schema import ClusterSchema, ImageSchema, SchedulingSchema, SharedStorageSchema


@pytest.mark.parametrize("config_file_name", ["slurm.required.yaml"])  # TODO, "slurm.simple.yaml"])
def test_cluster_schema_slurm(test_datadir, config_file_name):

    # https://github.com/marshmallow-code/marshmallow/issues/1126
    # TODO use yaml render_module: https://marshmallow.readthedocs.io/en/3.0/api_reference.html#marshmallow.Schema.Meta

    # Load cluster model from Yaml file
    input_yaml = load_yaml(test_datadir / config_file_name)
    print(input_yaml)
    cluster_config = ClusterSchema().load(input_yaml)
    print(cluster_config)

    # Re-create Yaml file from model and compare content
    output_json = ClusterSchema().dump(cluster_config)
    assert_that(json.dumps(input_yaml, sort_keys=True)).is_equal_to(json.dumps(output_json, sort_keys=True))

    # Print output yaml
    output_yaml = yaml.dump(output_json)
    print(output_yaml)

    # with open(config_file) as conf_file:
    #   input_file_content = conf_file.read()
    # assert_that(input_file_content).is_equal_to(cluster_config_yaml)
    # else:
    # _assert_files_are_equal(output_file, test_datadir / "expected_output.ini")

    # assert_that(cluster_config).is_equal_to(config_file)


@pytest.mark.parametrize(
    "os, custom_ami, failure_message",
    [
        (None, None, "Missing data for required field"),
        ("fake-os", "fake-custom-ami", None),
        ("fake-os", None, None),
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
        image_config = ImageSchema().load(image_schema)
        assert_that(image_config.os).is_equal_to(os)
        assert_that(image_config.id).is_equal_to(custom_ami)


DUMMY_REQUIRED_QUEUE = [
    {"Name": "queue1", "Networking": {"SubnetIds": ["subnet-xxx"]}, "ComputeResources": [{"InstanceType": "c5.xlarge"}]}
]

FAKE_QUEUE_LIST = [
    {
        "Name": "queue1",
        "Networking": {"SubnetIds": ["subnet-xxx"]},
        "ComputeResources": [{"InstanceType": "c5.xlarge"}, {"InstanceType": "c4.xlarge"}],
    },
    {
        "Name": "queue2",
        "Networking": {"SubnetIds": ["subnet-xxx"]},
        "ComputeResources": [{"InstanceType": "c5.2xlarge", "MaxCount": 5}, {"InstanceType": "c4.2xlarge"}],
    },
]


@pytest.mark.parametrize(
    "scheduler, queues_config, failure_message",
    [
        (None, None, "Missing data for required field"),
        (None, DUMMY_REQUIRED_QUEUE, None),
        ("fake-scheduler", DUMMY_REQUIRED_QUEUE, None),
    ],
)
def test_scheduling_schema(scheduler, queues_config, failure_message):
    scheduling_schema = {}
    if scheduler:
        scheduling_schema["Scheduler"] = scheduler
    if queues_config:
        scheduling_schema["Queues"] = queues_config

    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SchedulingSchema().load(scheduling_schema)
    else:
        image_config = SchedulingSchema().load(scheduling_schema)
        assert_that(image_config.scheduler).is_equal_to(scheduler if scheduler else "slurm")
        # assert_that(image_config.queues).con


DUMMY_EBS_STORAGE = {
    "MountDir": "/my/mount/point",
    "StorageType": "EBS",
    "Settings": {
        "VolumeType": "String",
        "Iops": 100,
        "Size": 150,
        "Encrypted": True,
        "KmsKeyId": "String",
        "SnapshotId": "String",
        "VolumeId": "String",
    },
}


@pytest.mark.parametrize(
    "mount_dir, volume_type, failure_message",
    [
        (None, None, "Missing MountDir"),
        ("mount-point", None, "Missing Settings"),
        ("mount-point", "gp2", None),
    ],
)
def test_ebs_schema(mount_dir, volume_type, failure_message):
    ebs_schema = {"StorageType": "EBS"}
    if mount_dir:
        ebs_schema["MountDir"] = mount_dir
    if volume_type:
        ebs_schema["Settings"] = {"VolumeType": volume_type}

    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SharedStorageSchema().load(ebs_schema)
    else:
        ebs_config = SharedStorageSchema().load(ebs_schema)
        assert_that(ebs_config).is_instance_of(EbsConfig)
        assert_that(ebs_config.mount_dir).is_equal_to(mount_dir)
        assert_that(ebs_config.volume_type).is_equal_to(volume_type)
