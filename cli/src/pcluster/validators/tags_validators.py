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
from pcluster.validators.common import FailureLevel, Validator


class ComputeResourceTagsValidator(Validator):
    """Compute resources tags validator."""

    def _validate(self, queue_name, compute_resource_name, cluster_tags, queue_tags):
        cluster_tags = {tag.key: tag.value for tag in cluster_tags} if cluster_tags else {}
        queue_tags = {tag.key: tag.value for tag in queue_tags} if queue_tags else {}

        if cluster_tags and queue_tags:
            cluster_keys = set(cluster_tags.keys())
            queue_keys = set(queue_tags.keys())
            overlapping_keys = sorted(list(cluster_keys.intersection(queue_keys)))
            if overlapping_keys:
                self._add_failure(
                    f"The following Tag keys are defined in both under `Tags` and `SlurmQueue/Tags`: {overlapping_keys}"
                    f" and will be overridden by the value set in `SlurmQueue/Tags` for "
                    f"ComputeResource '{compute_resource_name}' in queue '{queue_name}'.",
                    FailureLevel.WARNING,
                )
