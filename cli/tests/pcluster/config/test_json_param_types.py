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
import json
import os
from collections import OrderedDict

import pytest
from assertpy import assert_that

from pcluster.config.cfn_param_types import CfnSection
from pcluster.config.mappings import CLUSTER_HIT
from pcluster.config.param_types import SettingsParam, StorageData
from pcluster.config.pcluster_config import PclusterConfig
from tests.common import MockedBoto3Request
from tests.pcluster.config.utils import duplicate_config_file, get_mocked_pcluster_config

# Mocked responses for describe_instance_types boto3 calls
DESCRIBE_INSTANCE_TYPES_RESPONSES = {
    # Disable hyperthreading: supported
    # EFA: not supported
    "c4.xlarge": {
        "InstanceTypes": [
            {
                "InstanceType": "c4.xlarge",
                "VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2, "DefaultThreadsPerCore": 2},
                "NetworkInfo": {"EfaSupported": False, "MaximumNetworkCards": 1},
                "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
            }
        ]
    },
    # Disable hyperthreading: not supported
    # EFA: supported
    "g4dn.metal": {
        "InstanceTypes": [
            {
                "InstanceType": "g4dn.metal",
                "VCpuInfo": {"DefaultVCpus": 96},
                "GpuInfo": {"Gpus": [{"Name": "T4", "Manufacturer": "NVIDIA", "Count": 8}]},
                "NetworkInfo": {"EfaSupported": True, "MaximumNetworkCards": 1},
                "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
            }
        ]
    },
    # Disable hyperthreading: supported
    # EFA: supported
    "i3en.24xlarge": {
        "InstanceTypes": [
            {
                "InstanceType": "i3en.24xlarge",
                "VCpuInfo": {"DefaultVCpus": 96, "DefaultCores": 48, "DefaultThreadsPerCore": 2},
                "NetworkInfo": {"EfaSupported": True, "MaximumNetworkCards": 1},
                "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
            }
        ]
    },
    # Disable hyperthreading: not supported
    # EFA: not supported
    "t2.xlarge": {
        "InstanceTypes": [
            {
                "InstanceType": "t2.xlarge",
                "VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 4, "DefaultThreadsPerCore": 1},
                "NetworkInfo": {"EfaSupported": False, "MaximumNetworkCards": 1},
                "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
            }
        ]
    },
    # Disable hyperthreading: not supported
    # EFA: not supported
    "m6g.xlarge": {
        "InstanceTypes": [
            {
                "InstanceType": "m6g.xlarge",
                "VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 4, "DefaultThreadsPerCore": 1},
                "NetworkInfo": {"EfaSupported": False, "MaximumNetworkCards": 1},
                "ProcessorInfo": {"SupportedArchitectures": ["arm64"]},
            }
        ]
    },
    # Disable hyperthreading: not supported
    # EFA: not supported
    "t2.micro": {
        "InstanceTypes": [
            {
                "InstanceType": "t2.micro",
                "VCpuInfo": {"DefaultVCpus": 1, "DefaultCores": 1, "DefaultThreadsPerCore": 1},
                "NetworkInfo": {"EfaSupported": False, "MaximumNetworkCards": 1},
                "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
            }
        ]
    },
    # Disable hyperthreading: supported
    # EFA: supported
    # GPUs: yes
    "p4d.24xlarge": {
        "InstanceTypes": [
            {
                "InstanceType": "p4d.24xlarge",
                "VCpuInfo": {"DefaultVCpus": 96, "DefaultCores": 48, "DefaultThreadsPerCore": 2},
                "GpuInfo": {"Gpus": [{"Name": "A100", "Manufacturer": "NVIDIA", "Count": 8}]},
                "NetworkInfo": {"EfaSupported": True, "MaximumNetworkCards": 4},
                "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
            }
        ]
    },
}


@pytest.fixture(autouse=True)
def clear_cache():
    from pcluster.utils import Cache

    Cache.clear_all()


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.utils.boto3"


@pytest.mark.parametrize(
    "queues",
    [
        (["queue1"]),
        (["queue2"]),
        (["queue1", "queue2"]),
        ([]),
        (["queue3"]),
    ],
)
def test_config_to_json(capsys, boto3_stubber, test_datadir, pcluster_config_reader, queues):
    queue_settings = ",".join(queues)

    # Create a new configuration file from the initial one
    dst_config_file = "pcluster.config.{0}.ini".format("_".join(queues))
    duplicate_config_file(dst_config_file, test_datadir)

    # Created expected json params based on active queues
    expected_json_params = _prepare_json_config(queues, test_datadir)

    # Mock expected boto3 calls
    _mock_boto3(boto3_stubber, expected_json_params, head_node_instance_type="c4.xlarge")

    # Load config from created config file
    dst_config_file = pcluster_config_reader(dst_config_file, queue_settings=queue_settings)
    pcluster_config = PclusterConfig(config_file=dst_config_file, fail_on_file_absence=True)

    # Create json storage data from config
    storage_data = pcluster_config.to_storage()

    # Check that created json params match the expected ones
    assert_that(json.dumps(storage_data.json_params, indent=2, sort_keys=True)).is_equal_to(
        json.dumps(expected_json_params, indent=2, sort_keys=True)
    )

    readouterr = capsys.readouterr()
    assert_that(readouterr.err).is_equal_to("")

    pass


@pytest.mark.parametrize("queues", [(["queue1"]), (["queue2"]), (["queue1", "queue2"]), ([])])
def test_config_from_json(mocker, boto3_stubber, test_datadir, pcluster_config_reader, queues):
    def mock_get_avail_zone(subnet_id):
        # Mock az detection by returning a mock az if subnet has a value
        return "my-avail-zone" if subnet_id and subnet_id != "NONE" else None

    mocker.patch("pcluster.config.cfn_param_types.get_availability_zone_of_subnet", mock_get_avail_zone)

    # Created expected json params based on active queues
    expected_json_params = _prepare_json_config(queues, test_datadir)

    # Mock expected boto3 calls
    _mock_boto3(boto3_stubber, expected_json_params, head_node_instance_type="t2.micro")

    pcluster_config = get_mocked_pcluster_config(mocker, auto_refresh=False)
    cluster_section = CfnSection(CLUSTER_HIT, pcluster_config, section_label="default")
    cluster_section.from_storage(StorageData(cfn_params=[], json_params=expected_json_params))
    pcluster_config.add_section(cluster_section)
    pcluster_config.refresh()

    dashboard_section = pcluster_config.get_section("dashboard", "dashboard1")
    assert_that(dashboard_section).is_not_none()
    assert_that(dashboard_section.get_param_value("enable")).is_equal_to(False)

    for queue in queues:
        assert_that(pcluster_config.get_section("queue", queue)).is_not_none()
        _check_queue_section_from_json(
            expected_json_params, pcluster_config, pcluster_config.get_section("queue", queue)
        )


def _check_queue_section_from_json(json_config, pcluster_config, queue_section):
    """Check that the provided queue section has been loaded from Json config as expected."""
    queue_dict = json_config["cluster"]["queue_settings"][queue_section.label]
    _check_section(queue_section, queue_dict)

    instance_settings = queue_section.get_param("compute_resource_settings").value
    for label in instance_settings.split(","):
        instance_section = pcluster_config.get_section("compute_resource", label)
        instance_dict = queue_dict["compute_resource_settings"].get(label)
        _check_section(instance_section, instance_dict)


def _check_section(config_section, json_config_dict):
    """Compare a pcluster_config section with a json config section."""
    assert_that(config_section).is_not_none()
    assert_that(json_config_dict).is_not_none()
    for param_key, param_value in json_config_dict.items():
        param = config_section.get_param(param_key)
        if not isinstance(param, SettingsParam):
            assert_that(param_value).is_equal_to(config_section.get_param(param_key).value)
        else:
            check_settings(param.key, config_section, json_config_dict)


def check_settings(settings_param_key, config_section, json_config_dict):
    """Check that the order of labels in the provided settings param is maintained in the Json representation."""
    json_settings = ",".join([label for label, _ in json_config_dict[settings_param_key].items()])
    assert_that(json_settings).is_equal_to(config_section.get_param(settings_param_key).value)


def _prepare_json_config(queues, test_datadir):
    """Prepare the json configuration based on the selected queues."""
    json_config_path = os.path.join(str(test_datadir.parent), "s3_config.json")
    with open(json_config_path) as json_config_file:
        expected_json_params = json.load(json_config_file, object_pairs_hook=OrderedDict)

    expected_cluster_json_params = expected_json_params.get("cluster")
    queues_dict = expected_cluster_json_params.get("queue_settings")
    expected_cluster_json_params.pop("queue_settings")
    expected_json_queue_settings = OrderedDict({queue_label: queues_dict[queue_label] for queue_label in queues})
    expected_cluster_json_params["default_queue"] = queues[0] if queues else None
    if expected_json_queue_settings:
        expected_cluster_json_params["queue_settings"] = expected_json_queue_settings
    return expected_json_params


def _mock_boto3(boto3_stubber, expected_json_params, head_node_instance_type=None):
    """Mock the boto3 client based on the expected json configuration."""
    expected_json_queue_settings = expected_json_params["cluster"].get("queue_settings", {})
    mocked_requests = []
    instance_types = []
    # One describe_instance_type for the Head node
    if head_node_instance_type:
        instance_types.append(head_node_instance_type)

    # One describe_instance_type per compute resource
    for _, queue in expected_json_queue_settings.items():
        for _, compute_resource in queue.get("compute_resource_settings", {}).items():
            if compute_resource["instance_type"] not in instance_types:
                instance_types.append(compute_resource["instance_type"])

    for instance_type in instance_types:
        mocked_requests.append(
            MockedBoto3Request(
                method="describe_instance_types",
                response=DESCRIBE_INSTANCE_TYPES_RESPONSES[instance_type],
                expected_params={"InstanceTypes": [instance_type]},
            )
        )
    boto3_stubber("ec2", mocked_requests)
