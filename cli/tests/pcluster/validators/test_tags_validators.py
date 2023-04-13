# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from pcluster.config.cluster_config import Tag
from pcluster.validators.tags_validators import ComputeResourceTagsValidator
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "cluster_tags, queue_tags, compute_resource_tags, expected_message",
    [
        (
            [Tag("key1", "value1"), Tag("key2", "value2"), Tag("key3", "value3")],
            [Tag("key1", "value1"), Tag("key2", "value2"), Tag("key3", "value3")],
            None,
            "The following Tag keys are defined in both under `Tags` and `SlurmQueue/Tags`: ['key1', 'key2', 'key3'] "
            "and will be overridden by the value set in `SlurmQueue/Tags` for ComputeResource 'dummy_compute_resource' "
            "in queue 'dummy_queue'.",
        ),
        (
            [Tag("key1", "value1"), Tag("key2", "value2"), Tag("key3", "value3")],
            [Tag("key1", "value1"), Tag("key2", "value2"), Tag("key3", "value3")],
            [Tag("key1", "value1"), Tag("key2", "value2"), Tag("key3", "value3")],
            "The following Tag keys are defined under `Tags`, `SlurmQueue/Tags` and `SlurmQueue/ComputeResources/Tags`:"
            " ['key1', 'key2', 'key3'] "
            "and will be overridden by the value set in `SlurmQueue/ComputeResources/Tags` for ComputeResource "
            "'dummy_compute_resource' "
            "in queue 'dummy_queue'.",
        ),
        (
            [Tag("key1", "value1"), Tag("clusterkey2", "value2"), Tag("clusterkey3", "value3")],
            [Tag("key1", "value1"), Tag("queuekey2", "value2"), Tag("queuekey3", "value3")],
            [Tag("key1", "value1"), Tag("computekey2", "value2"), Tag("computekey3", "value3")],
            "The following Tag keys are defined under `Tags`, `SlurmQueue/Tags` and `SlurmQueue/ComputeResources/Tags`:"
            " ['key1'] "
            "and will be overridden by the value set in `SlurmQueue/ComputeResources/Tags` for ComputeResource "
            "'dummy_compute_resource' "
            "in queue 'dummy_queue'.",
        ),
        (
            [Tag("key1", "value1"), Tag("key2", "value2"), Tag("key3", "value3")],
            [Tag("key4", "value1"), Tag("key5", "value2"), Tag("key6", "value3")],
            None,
            None,
        ),
        (
            [Tag("key1", "value1"), Tag("key2", "value2")],
            [Tag("key1", "value2"), Tag("key3", "value2")],
            None,
            "The following Tag keys are defined in both under `Tags` and `SlurmQueue/Tags`: ['key1'] and will be "
            "overridden by the value set in `SlurmQueue/Tags` for ComputeResource 'dummy_compute_resource' in queue "
            "'dummy_queue'.",
        ),
        (
            [Tag("key1", "value1"), Tag("key2", "value2"), Tag("key3", "value3")],
            None,
            None,
            None,
        ),
        (
            None,
            [Tag("key1", "value1"), Tag("key2", "value2"), Tag("key3", "value3")],
            None,
            None,
        ),
        (
            None,
            None,
            None,
            None,
        ),
        (
            [Tag("key1", "value1")],
            [Tag("key2", "value2")],
            [Tag("key3", "value3")],
            None,
        ),
        (
            None,
            [Tag("key1", "value1"), Tag("key2", "value2")],
            [Tag("key1", "value1"), Tag("key3", "value3")],
            "The following Tag keys are defined in both under `SlurmQueue/Tags` and `SlurmQueue/ComputeResources/Tags`:"
            " ['key1'] and will be overridden by the value set in `SlurmQueue/ComputeResources/Tags` for "
            "ComputeResource 'dummy_compute_resource' in queue 'dummy_queue'.",
        ),
        (
            [Tag("key1", "value1"), Tag("key2", "value2")],
            None,
            [Tag("key1", "value1"), Tag("key3", "value3")],
            "The following Tag keys are defined in both under `Tags` and `SlurmQueue/ComputeResources/Tags`:"
            " ['key1'] and will be overridden by the value set in `SlurmQueue/ComputeResources/Tags` for "
            "ComputeResource 'dummy_compute_resource' in queue 'dummy_queue'.",
        ),
        (
            [Tag(f"key{i}", f"value{i}") for i in range(0, 41)],
            None,
            None,
            "The number of tags (41) associated with ComputeResource 'dummy_compute_resource' in queue 'dummy_queue' "
            "has exceeded the limit of 40.",
        ),
        (
            [Tag(f"key{i}", f"value{i}") for i in range(0, 20)],
            [Tag(f"key{i}", f"value{i}") for i in range(20, 41)],
            None,
            "The number of tags (41) associated with ComputeResource 'dummy_compute_resource' in queue 'dummy_queue' "
            "has exceeded the limit of 40.",
        ),
        (
            [Tag(f"key{i}", f"value{i}") for i in range(0, 20)],
            None,
            [Tag(f"key{i}", f"value{i}") for i in range(20, 41)],
            "The number of tags (41) associated with ComputeResource 'dummy_compute_resource' in queue 'dummy_queue' "
            "has exceeded the limit of 40.",
        ),
        (
            [Tag(f"key{i}", f"value{i}") for i in range(0, 10)],
            [Tag(f"key{i}", f"value{i}") for i in range(10, 20)],
            [Tag(f"key{i}", f"value{i}") for i in range(20, 41)],
            "The number of tags (41) associated with ComputeResource 'dummy_compute_resource' in queue 'dummy_queue' "
            "has exceeded the limit of 40.",
        ),
        (
            [Tag(f"key{i}", f"value{i}") for i in range(0, 10)],
            [Tag(f"key{i}", f"value{i}") for i in range(10, 40)],
            [Tag("key0", "value0")],
            "The following Tag keys are defined in both under `Tags` and `SlurmQueue/ComputeResources/Tags`: ['key0'] "
            "and will be overridden by the value set in `SlurmQueue/ComputeResources/Tags` for ComputeResource "
            "'dummy_compute_resource' in queue 'dummy_queue'.",
        ),
    ],
)
def test_compute_resource_tags_validator(cluster_tags, queue_tags, compute_resource_tags, expected_message):
    actual_failures = ComputeResourceTagsValidator().execute(
        "dummy_queue", "dummy_compute_resource", cluster_tags, queue_tags, compute_resource_tags
    )
    assert_failure_messages(actual_failures, expected_message)
