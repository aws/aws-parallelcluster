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
import re
from datetime import datetime

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.aws_resources import InstanceInfo, StackInfo
from pcluster.aws.common import AWSClientError
from pcluster.constants import CW_LOGS_CFN_PARAM_NAME, OS_MAPPING, PCLUSTER_NODE_TYPE_TAG, PCLUSTER_VERSION_TAG


class ClusterStack(StackInfo):
    """Class representing a running stack associated to a Cluster."""

    def __init__(self, stack_data: dict):
        """Init stack info."""
        super().__init__(stack_data)

    @property
    def cluster_name(self):
        """Return cluster name associated to this cluster."""
        return self.name

    @property
    def version(self):
        """Return the version of ParallelCluster used to create the stack."""
        return self.get_tag(PCLUSTER_VERSION_TAG)

    @property
    def s3_bucket_name(self):
        """Return the name of the bucket used to store cluster information."""
        return self._get_param("ResourcesS3Bucket")

    @property
    def s3_artifact_directory(self):
        """Return the artifact directory of the bucket used to store cluster information."""
        return self._get_param("ArtifactS3RootDirectory")

    @property
    def head_node_user(self):
        """Return the output storing cluster user."""
        return self._get_param("ClusterUser")

    @property
    def head_node_ip(self):
        """Return the IP to be used to connect to the head node, public or private."""
        return self._get_output("HeadNodePublicIP") or self._get_output("HeadNodePrivateIP")

    @property
    def scheduler(self):
        """Return the scheduler used in the cluster."""
        return self._get_param("Scheduler")

    @property
    def log_group_name(self):
        """Return the log group name used in the cluster."""
        return self._get_param(CW_LOGS_CFN_PARAM_NAME)

    @property
    def original_config_version(self):
        """Return the log group name used in the cluster."""
        return self._get_param("ConfigVersion")

    def delete(self):
        """Delete stack."""
        AWSApi.instance().cfn.delete_stack(self.name)

    @property
    def batch_compute_environment(self):
        """Return Batch compute environment."""
        return self._get_output("BatchComputeEnvironmentArn")


class ClusterInstance(InstanceInfo):
    """Object to store cluster Instance info, initialized with a describe_instances call and other cluster info."""

    def __init__(self, instance_data: dict):
        super().__init__(instance_data)

    @property
    def default_user(self) -> str:
        """Get the default user for the instance."""
        return OS_MAPPING.get(self.os, []).get("user", None)

    @property
    def os(self) -> str:
        """Return os of the instance."""
        os = None
        attributes_tag = self._get_tag("parallelcluster:attributes")
        if attributes_tag:
            # tag is in the form "{BaseOS}, {Scheduler}, {Version}, {Architecture}"
            os = attributes_tag.split(",")[0].strip()
        return os

    @property
    def node_type(self) -> str:
        """Return os of the instance."""
        return self._get_tag(PCLUSTER_NODE_TYPE_TAG)

    def _get_tag(self, tag_key: str):
        return next(iter([tag["Value"] for tag in self._tags if tag["Key"] == tag_key]), None)


class FiltersParserError(Exception):
    """Represent export logs filter errors."""

    def __init__(self, message: str):
        super().__init__(message)


class FiltersParser:
    """Class to parse filters."""

    def __init__(self, filters: str = None):
        if filters:
            self.filters_list = re.findall(r"Name=([^=,]+),Values=([^= ]+)(?: |$)", filters)
            if not self.filters_list:
                raise FiltersParserError(f"Invalid filters {filters}. They must be in the form Name=xxx,Values=yyy .")
        else:
            self.filters_list = []

    def validate(self):
        """Validate filters."""
        pass


class ExportClusterLogsFiltersParser(FiltersParser):
    """Class to manage export cluster logs filters."""

    def __init__(self, log_group_name: str, filters: str = None):
        super().__init__(filters)
        self._log_group_name = log_group_name
        self._start_time = None
        self.end_time = int(datetime.now().timestamp() * 1000)
        self.log_stream_prefix = None

        for name, values in self.filters_list:
            if "," in values:
                raise FiltersParserError(f"Filter {name} doesn't accept comma separated strings as value.")

            filter_name = name.replace("-", "_")
            if name in ["start-time", "end-time"]:
                try:
                    filter_value = int(values) * 1000
                except Exception:
                    raise FiltersParserError(f"Unable to use {values} filter, the expected format is Unix epoch")
            elif name == "private-ip-address":
                filter_name = "log_stream_prefix"
                filter_value = f"ip-{values.replace('.', '-')}"
            else:
                filter_value = values

            if not hasattr(self, filter_name):
                raise FiltersParserError(f"Filter {name} not supported.")
            setattr(self, filter_name, filter_value)

    @property
    def start_time(self):
        """Get start time filter."""
        if not self._start_time:
            try:
                self._start_time = AWSApi.instance().logs.describe_log_group(self._log_group_name).get("creationTime")
            except AWSClientError as e:
                raise FiltersParserError(
                    f"Unable to retrieve creation time of log group {self._log_group_name}, {str(e)}"
                )
        return self._start_time

    @start_time.setter
    def start_time(self, value):
        """Set start_time value."""
        self._start_time = value

    def validate(self):
        """Check filters consistency."""
        if self.start_time >= self.end_time:
            raise FiltersParserError("Start time must be earlier than end time.")

        event_in_window = AWSApi.instance().logs.filter_log_events(
            log_group_name=self._log_group_name, start_time=self.start_time, end_time=self.end_time
        )
        if not event_in_window:
            raise FiltersParserError(
                f"No log events in the log group {self._log_group_name} in interval starting "
                f"at {self.start_time} and ending at {self.end_time}."
            )


class ListClusterLogsFiltersParser(FiltersParser):
    """Class to manage list cluster logs filters."""

    def __init__(self, log_group_name: str, filters: str = None):
        super().__init__(filters)
        self._log_group_name = log_group_name
        self.log_stream_prefix = None

        for name, values in self.filters_list:
            if "," in values:
                raise FiltersParserError(f"Filter {name} doesn't accept comma separated strings as value.")

            filter_name = name.replace("-", "_")
            if name == "private-ip-address":
                filter_name = "log_stream_prefix"
                filter_value = f"ip-{values.replace('.', '-')}"
            else:
                filter_value = values

            if not hasattr(self, filter_name):
                raise FiltersParserError(f"Filter {name} not supported.")
            setattr(self, filter_name, filter_value)
