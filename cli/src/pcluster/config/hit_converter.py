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
from pcluster.utils import get_file_section_name

LOGGER = logging.getLogger(__name__)


class HitConverter:
    """Utility class which takes care of ensuring backward compatibility with the pre-HIT configuration model."""

    def __init__(self, pcluster_config):
        self.pcluster_config = pcluster_config

    def convert(self, prepare_to_file=False):
        """
        Convert the pcluster_config instance from pre-HIT to HIT configuration model.

        Currently, the conversion is performed only if the configured scheduler is Slurm.
        :return False and the reason if the conversion cannot be done, (True, None) otherwise.
        """
        conversion_done = False
        reason = None
        if self.pcluster_config.cluster_model == ClusterModel.HIT:
            reason = "Conversion not required, the configuration file format already supports multiple instance types."
        else:
            # Copying sections referred from cluster or global ones
            self._store_original_sections()

            # Save current autorefresh settings and disable autorefresh
            auto_refresh = self.pcluster_config.auto_refresh
            self.pcluster_config.auto_refresh = False

            sit_cluster_section = self.pcluster_config.get_section("cluster")
            scheduler = sit_cluster_section.get_param_value("scheduler")

            if scheduler != "slurm":
                reason = "Conversion not required, scheduler is {0}.".format(scheduler)
                LOGGER.debug(reason)
            else:
                LOGGER.debug(
                    "Slurm scheduler used with Single Instance Type configuration model. Starting conversion...",
                )
                hit_cluster_section = ClusterCfnSection(
                    section_definition=mappings.CLUSTER_HIT,
                    pcluster_config=self.pcluster_config,
                    section_label=sit_cluster_section.label,
                )

                # Remove SIT Cluster section and add HIT Section
                self.pcluster_config.remove_section(sit_cluster_section.key, sit_cluster_section.label)
                self.pcluster_config.add_section(hit_cluster_section)

                # Create default queue section
                queue_section = QueueJsonSection(
                    mappings.QUEUE, self.pcluster_config, section_label="compute", parent_section=hit_cluster_section
                )
                self.pcluster_config.add_section(queue_section)
                hit_cluster_section.get_param("queue_settings").value = "compute"

                self._copy_param_value(
                    sit_cluster_section.get_param("cluster_type"), queue_section.get_param("compute_type")
                )
                self._copy_param_value(
                    sit_cluster_section.get_param("enable_efa"),
                    queue_section.get_param("enable_efa"),
                    "compute" == sit_cluster_section.get_param("enable_efa").value,
                )
                self._copy_param_value(
                    sit_cluster_section.get_param("enable_efa_gdr"),
                    queue_section.get_param("enable_efa_gdr"),
                    "compute" == sit_cluster_section.get_param("enable_efa_gdr").value,
                )
                self._copy_param_value(
                    sit_cluster_section.get_param("placement_group"), queue_section.get_param("placement_group")
                )

                # Print a warning for unsupported parameters
                if sit_cluster_section.get_param_value("placement") == "cluster":
                    LOGGER.debug(
                        "Warning: 'placement = cluster' is not supported when using multiple instance types.",
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

                # SIT initial size is copied to min_count or to initial_count based on SIT maintain_initial_size
                sit_initial_size_param = sit_cluster_section.get_param("initial_queue_size")
                sit_maintain_initial_size_param = sit_cluster_section.get_param_value("maintain_initial_size")
                compute_resource_size_param_key = "min_count" if sit_maintain_initial_size_param else "initial_count"
                self._copy_param_value(
                    sit_initial_size_param, compute_resource_section.get_param(compute_resource_size_param_key)
                )

                # Copy all cluster params except enable_efa and enable_efa_gdr (already set at queue level)
                hit_cluster_param_keys = [
                    param_key
                    for param_key in hit_cluster_section.params.keys()
                    if param_key not in ["enable_efa", "enable_efa_gdr"]
                ]
                for param_key in sit_cluster_section.params.keys():
                    if param_key in hit_cluster_param_keys:
                        self._copy_param_value(
                            sit_cluster_section.get_param(param_key), hit_cluster_section.get_param(param_key)
                        )

                # Restore cluster nested sections, with owner modified
                self._restore_original_sections(hit_cluster_section)

                # Refresh configuration and restore initial autorefresh settings
                self.pcluster_config.refresh()
                self.pcluster_config.auto_refresh = auto_refresh

                self.clean_config_parser(hit_cluster_section)
                if prepare_to_file:
                    self._prepare_to_file()

                LOGGER.debug("Conversion to HIT completed successfully.")
                conversion_done = True

        return conversion_done, reason

    def _copy_param_value(self, old_param, new_param, new_value=None):
        """Copy the value from the old param to the new one."""
        new_param.value = new_value if new_value is not None else old_param.value

    @staticmethod
    def _reset_config_params(section, parameters_to_remove):
        for param_key in parameters_to_remove:
            param = section.get_param(param_key)
            param.value = param.get_default_value()

    def _prepare_to_file(self):
        """Reset some parameters from config file since their values can be inferred at runtime."""
        # disable_hyperthreading will get its value from cluster section
        queue_section = self.pcluster_config.get_section("queue", "compute")
        self._reset_config_params(queue_section, ["disable_hyperthreading"])

        # Remove initial_count if not needed
        compute_section = self.pcluster_config.get_section("compute_resource", "default")
        if compute_section.get_param_value("initial_count") == compute_section.get_param_value("min_count"):
            self._reset_config_params(compute_section, ["initial_count"])

        # cluster's disable_hyperthreading's HIT default is None instead of False
        cluster_section = self.pcluster_config.get_section("cluster")
        if not cluster_section.get_param_value("disable_hyperthreading"):
            self._reset_config_params(cluster_section, ["disable_hyperthreading"])

    def _store_original_sections(self):
        """
        Store original default sections from configuration.

        This operation is needed because default sections are overridden when the cluster section is created
        and other sections must change the owner.
        """
        self._cluster_nested_sections = []
        for section_key in self.pcluster_config.get_section_keys(
            include_global_sections=True, excluded_keys=["cluster"]
        ):
            for _, section in self.pcluster_config.get_sections(section_key).items():
                self._cluster_nested_sections.append(section)

    def _restore_original_sections(self, hit_cluster_section):
        """
        Restore the original default sections in the configuration, making them children of the new cluster section.

        :param hit_cluster_section: The new HIT cluster section
        """
        for section in self._cluster_nested_sections:
            if section.autocreate:
                # remove default sections
                self.pcluster_config.remove_section(section.key, "default")
                # restore sections
                self.pcluster_config.add_section(section)

            if section.key not in self.pcluster_config.get_global_section_keys():
                # change owner of sections nested into the cluster one.
                section.parent_section = hit_cluster_section

    def clean_config_parser(self, hit_cluster_section):
        """
        Clean the attached config parser from old attributes.

        This operation is needed to avoid writing back unsupported parameters (like compute_instance_type) to the
        configuration file
        :param hit_cluster_section: The new HIT cluster section
        """
        config_parser = self.pcluster_config.config_parser
        if config_parser:
            config_parser.remove_section(get_file_section_name("cluster", hit_cluster_section.label))
