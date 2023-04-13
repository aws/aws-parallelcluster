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
from pcluster.constants import MAX_TAGS_COUNT
from pcluster.validators.common import FailureLevel, Validator


class ComputeResourceTagsValidator(Validator):
    """Compute resources tags validator."""

    def _validate(self, queue_name, compute_resource_name, cluster_tags, queue_tags, compute_resource_tags):
        cluster_tag_keys = {tag.key for tag in cluster_tags} if cluster_tags else set()
        queue_tag_keys = {tag.key for tag in queue_tags} if queue_tags else set()
        compute_resource_tag_keys = {tag.key for tag in compute_resource_tags} if compute_resource_tags else set()

        overlapping_keys = cluster_tag_keys & queue_tag_keys & compute_resource_tag_keys
        key_count = len(cluster_tag_keys | queue_tag_keys | compute_resource_tag_keys)
        overlapping_keys_list = sorted(list(overlapping_keys))
        queue_cluster_overlapping_keys_list = sorted(list(cluster_tag_keys & queue_tag_keys - overlapping_keys))
        compute_resource_queue_overlapping_key_list = sorted(
            list(queue_tag_keys & compute_resource_tag_keys - overlapping_keys)
        )
        cluster_compute_resource_overlapping_key_list = sorted(
            list(cluster_tag_keys & compute_resource_tag_keys - overlapping_keys)
        )

        if overlapping_keys_list:
            self._add_failure(
                "The following Tag keys are defined under `Tags`, `SlurmQueue/Tags` and "
                f"`SlurmQueue/ComputeResources/Tags`: {overlapping_keys_list}"
                " and will be overridden by the value set in `SlurmQueue/ComputeResources/Tags` for "
                f"ComputeResource '{compute_resource_name}' in queue '{queue_name}'.",
                FailureLevel.WARNING,
            )
        if queue_cluster_overlapping_keys_list:
            self._add_failure(
                "The following Tag keys are defined in both under `Tags` and `SlurmQueue/Tags`: "
                f"{queue_cluster_overlapping_keys_list} and will be overridden by the value set in `SlurmQueue/Tags` "
                f"for ComputeResource '{compute_resource_name}' in queue '{queue_name}'.",
                FailureLevel.WARNING,
            )
        if compute_resource_queue_overlapping_key_list:
            self._add_failure(
                "The following Tag keys are defined in both under `SlurmQueue/Tags` and "
                f"`SlurmQueue/ComputeResources/Tags`: {compute_resource_queue_overlapping_key_list} and will be "
                f"overridden by the value set in `SlurmQueue/ComputeResources/Tags` for "
                f"ComputeResource '{compute_resource_name}' in queue '{queue_name}'.",
                FailureLevel.WARNING,
            )

        if cluster_compute_resource_overlapping_key_list:
            self._add_failure(
                "The following Tag keys are defined in both under `Tags` and `SlurmQueue/ComputeResources/Tags`: "
                f"{cluster_compute_resource_overlapping_key_list} and will be overridden by the value set in "
                f"`SlurmQueue/ComputeResources/Tags` for ComputeResource '{compute_resource_name}' in queue"
                f" '{queue_name}'.",
                FailureLevel.WARNING,
            )

        if key_count > MAX_TAGS_COUNT:
            self._add_failure(
                f"The number of tags ({key_count}) associated with ComputeResource '{compute_resource_name}' in queue "
                f"'{queue_name}' has exceeded the limit of {MAX_TAGS_COUNT}.",
                FailureLevel.ERROR,
            )
