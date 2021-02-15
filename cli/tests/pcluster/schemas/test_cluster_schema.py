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

from common.utils import load_yaml_dict
from pcluster.schemas.cluster_schema import ClusterSchema, ImageSchema, SlurmSchema


def _check_cluster_schema(test_datadir, config_file_name):
    # https://github.com/marshmallow-code/marshmallow/issues/1126
    # TODO use yaml render_module: https://marshmallow.readthedocs.io/en/3.0/api_reference.html#marshmallow.Schema.Meta

    # Load cluster model from Yaml file
    input_yaml = load_yaml_dict(test_datadir / config_file_name)
    print(input_yaml)
    cluster = ClusterSchema().load(input_yaml)
    print(cluster)

    # Re-create Yaml file from model and compare content
    output_json = ClusterSchema().dump(cluster)
    assert_that(json.dumps(input_yaml, sort_keys=True)).is_equal_to(json.dumps(output_json, sort_keys=True))

    # Print output yaml
    output_yaml = yaml.dump(output_json)
    print(output_yaml)


@pytest.mark.parametrize("config_file_name", ["slurm.required.yaml", "slurm.full.yaml"])
def test_cluster_schema_slurm(test_datadir, config_file_name):
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


DUMMY_REQUIRED_QUEUE = [
    {
        "Name": "queue1",
        "Networking": {"SubnetIds": ["subnet-12345678"]},
        "ComputeResources": [{"Name": "compute_resource1", "InstanceType": "c5.xlarge"}],
    }
]

FAKE_QUEUE_LIST = [
    {
        "Name": "queue1",
        "Networking": {"SubnetIds": ["subnet-12345678"]},
        "ComputeResources": [{"InstanceType": "c5.xlarge"}, {"InstanceType": "c4.xlarge"}],
    },
    {
        "Name": "queue2",
        "Networking": {"SubnetIds": ["subnet-12345678"]},
        "ComputeResources": [{"InstanceType": "c5.2xlarge", "MaxCount": 5}, {"InstanceType": "c4.2xlarge"}],
    },
]


@pytest.mark.parametrize(
    "queues, failure_message",
    [
        (None, "Missing data for required field"),
        (DUMMY_REQUIRED_QUEUE, None),
    ],
)
def test_slurm_scheduling_schema(queues, failure_message):
    scheduling_schema = {}
    if queues:
        scheduling_schema["Queues"] = queues

    if failure_message:
        with pytest.raises(ValidationError, match=failure_message):
            SlurmSchema().load(scheduling_schema)
    else:
        SlurmSchema().load(scheduling_schema)


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

"""
# Mount directory is going to be tested in test for shared storage
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
"""
