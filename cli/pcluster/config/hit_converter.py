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
import logging

from pcluster.cluster_model import ClusterModel
from pcluster.config import mappings
from pcluster.config.cfn_param_types import ClusterCfnSection
from pcluster.config.json_param_types import JsonSection, QueueJsonSection

LOGGER = logging.getLogger(__name__)


class HitConverter:
    """Utility class which takes care of ensuring backward compatibility with the pre-HIT configuration model."""

    def __init__(self, pcluster_config):
        self.pcluster_config = pcluster_config

    def convert(self):
        """
        Convert the pcluster_config instance from pre-HIT to HIT configuration model.

        Currently, the conversion is performed only if the configured scheduler is Slurm.
        """
        if self.pcluster_config.cluster_model != ClusterModel.HIT:
            sit_cluster_section = self.pcluster_config.get_section("cluster")

            scheduler = sit_cluster_section.get_param_value("scheduler")

            if scheduler == "slurm":
                LOGGER.debug("Slurm scheduler used with SIT configuration model. Conversion in progress.")
                hit_cluster_section = ClusterCfnSection(
                    section_definition=mappings.CLUSTER_HIT,
                    pcluster_config=self.pcluster_config,
                    section_label=sit_cluster_section.label,
                )

                # Remove SIT Cluster section and add HIT Section
                self.pcluster_config.remove_section(sit_cluster_section.key, sit_cluster_section.label)
                self.pcluster_config.add_section(hit_cluster_section)

                # Save current autorefresh settings and disable autorefresh
                auto_refresh = self.pcluster_config.auto_refresh
                self.pcluster_config.auto_refresh = False

                # Create default queue section
                queue_section = QueueJsonSection(
                    mappings.QUEUE, self.pcluster_config, section_label="default", parent_section=sit_cluster_section
                )
                self.pcluster_config.add_section(queue_section)
                hit_cluster_section.get_param("queue_settings").value = "default"

                self._copy_param_value(
                    sit_cluster_section.get_param("cluster_type"), queue_section.get_param("compute_type")
                )
                self._copy_param_value(
                    sit_cluster_section.get_param("enable_efa"),
                    queue_section.get_param("enable_efa"),
                    "compute" == sit_cluster_section.get_param("enable_efa").value,
                )
                self._copy_param_value(
                    sit_cluster_section.get_param("disable_hyperthreading"),
                    queue_section.get_param("disable_hyperthreading"),
                )
                self._copy_param_value(
                    sit_cluster_section.get_param("placement_group"), queue_section.get_param("placement_group")
                )

                # Create default single compute resource
                compute_resource_section = JsonSection(
                    mappings.COMPUTE_RESOURCE,
                    self.pcluster_config,
                    section_label="default",
                    parent_section=queue_section,
                )
                self.pcluster_config.add_section(compute_resource_section)
                queue_section.get_param("compute_resource_settings").value = "default"

                self._copy_param_value(
                    sit_cluster_section.get_param("compute_instance_type"),
                    compute_resource_section.get_param("instance_type"),
                )

                self._copy_param_value(
                    sit_cluster_section.get_param("max_queue_size"), compute_resource_section.get_param("max_count")
                )

                self._copy_param_value(
                    sit_cluster_section.get_param("spot_price"), compute_resource_section.get_param("spot_price")
                )

                if sit_cluster_section.get_param_value("maintain_initial_size"):
                    self._copy_param_value(
                        sit_cluster_section.get_param("initial_queue_size"),
                        compute_resource_section.get_param("min_count"),
                    )

                # Copy all cluster params except enable_efa and disable_hyperthreading (already set at queue level)
                hit_cluster_param_keys = [
                    param_key
                    for param_key in hit_cluster_section.params.keys()
                    if param_key not in ["disable_hyperthreading", "enable_efa"]
                ]
                for param_key in sit_cluster_section.params.keys():
                    if param_key in hit_cluster_param_keys:
                        self._copy_param_value(
                            sit_cluster_section.get_param(param_key), hit_cluster_section.get_param(param_key)
                        )

                # Refresh configuration and restore initial autorefresh settings
                self.pcluster_config.refresh()
                self.pcluster_config.auto_refresh = auto_refresh

    def _copy_param_value(self, old_param, new_param, new_value=None):
        """Copy the value from the old param to the new one."""
        new_param.value = new_value if new_value is not None else old_param.value
