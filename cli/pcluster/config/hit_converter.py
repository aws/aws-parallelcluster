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
from pcluster.config import mappings
from pcluster.config.json_param_types import JsonSection


class HitConverter:
    """Utility class which takes care of ensuring backward compatibility with the pre-HIT configuration model."""

    def __init__(self, pcluster_config):
        self.pcluster_config = pcluster_config

    def convert(self):
        """
        Convert the pcluster_config instance from pre-HIT to HIT configuration model.

        Currently, the conversion is performed only if the configured scheduler is Slurm.
        """
        cluster_section = self.pcluster_config.get_section("cluster")
        scheduler = cluster_section.get_param_value("scheduler")
        queue_settings = cluster_section.get_param_value("queue_settings")

        if scheduler == "slurm" and not queue_settings:
            auto_refresh = self.pcluster_config.auto_refresh
            # Autorefresh is disabled during conversion
            self.pcluster_config.auto_refresh = False

            # Default single queue
            queue_section = JsonSection(
                mappings.QUEUE, self.pcluster_config, section_label="default", parent_section=cluster_section
            )
            self.pcluster_config.add_section(queue_section)

            self._move_param_value(cluster_section.get_param("cluster_type"), queue_section.get_param("compute_type"))
            self._move_param_value(
                cluster_section.get_param("enable_efa"),
                queue_section.get_param("enable_efa"),
                "compute" == cluster_section.get_param("enable_efa").value,
            )
            self._move_param_value(
                queue_section.get_param("disable_hyperthreading"), queue_section.get_param("disable_hyperthreading")
            )
            self._move_param_value(
                queue_section.get_param("placement_group"), queue_section.get_param("placement_group")
            )

            # Default single compute resource
            compute_resource_section = JsonSection(
                mappings.COMPUTE_RESOURCE, self.pcluster_config, section_label="default", parent_section=queue_section
            )
            self.pcluster_config.add_section(compute_resource_section)

            self._move_param_value(
                cluster_section.get_param("compute_instance_type"), compute_resource_section.get_param("instance_type")
            )

            self._move_param_value(
                cluster_section.get_param("max_queue_size"), compute_resource_section.get_param("max_count")
            )

            self._move_param_value(
                cluster_section.get_param("spot_price"), compute_resource_section.get_param("spot_price")
            )

            if cluster_section.get_param_value("maintain_initial_size"):
                self._move_param_value(
                    cluster_section.get_param("initial_queue_size"), compute_resource_section.get_param("min_count")
                )

            self.pcluster_config.auto_refresh = auto_refresh

    def _move_param_value(self, old_param, new_param, new_value=None):
        """Copy the value from the old param to the new one and reset old param to its default value."""
        new_param.value = new_value if new_value is not None else old_param.value
        old_param.reset_value()
