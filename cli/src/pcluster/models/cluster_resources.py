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
import datetime
import itertools
import re
from dataclasses import dataclass
from typing import List

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.aws_resources import InstanceInfo, StackInfo
from pcluster.constants import CW_LOGS_CFN_PARAM_NAME, OS_MAPPING, PCLUSTER_NODE_TYPE_TAG, PCLUSTER_VERSION_TAG
from pcluster.models.common import FiltersParserError, LogGroupTimeFiltersParser, get_all_stack_events


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
    def scheduler(self):
        """Return the scheduler used in the cluster."""
        return self._get_param("Scheduler")

    @property
    def log_group_name(self):
        """Return the log group name used in the cluster."""
        return self._get_param(CW_LOGS_CFN_PARAM_NAME)

    @property
    def original_config_version(self):
        """Return the version of the original config used to generate the stack in the cluster."""
        return self._get_param("ConfigVersion")

    @property
    def official_ami(self):
        """Return the original official AMI."""
        return self._get_param("OfficialAmi")

    def delete(self):
        """Delete stack."""
        AWSApi.instance().cfn.delete_stack(self.name)

    @property
    def batch_compute_environment(self):
        """Return Batch compute environment."""
        return self._get_output("BatchComputeEnvironmentArn")

    def _get_failure_reason(self):
        """Reason of the failure when the cluster_status is in CREATE_FAILED."""

        def _is_failed_wait(event):
            if (
                event.get("ResourceType") == "AWS::CloudFormation::WaitCondition"
                and event.get("ResourceStatus") == "CREATE_FAILED"
            ):
                return True
            return False

        stack_events = list(itertools.chain.from_iterable(get_all_stack_events(self.name)))
        failure_event = next(filter(_is_failed_wait, stack_events), None)
        return failure_event.get("ResourceStatusReason") if failure_event else None

    def get_cluster_creation_failure(self):
        """Get error code and error reasons for cluster creation failure."""

        @dataclass
        class ClusterCreationFailure:
            """Represent the object holding the data of ClusterCreationFailure."""

            failure_code: str
            api_failure_reason: str
            cfn_failure_reason: str

        cluster_creation_failures = [
            ClusterCreationFailure(
                "AmiVersionMismatch",
                "ParallelCluster version of the custom AMI is different than the cookbook. Please make them "
                "consistent.",
                "This AMI was created with",
            ),
            ClusterCreationFailure(
                "InvalidAmi",
                "The custom AMI is invalid. It needs to be created using build-image command by providing your AMI as "
                "parent image.",
                "This AMI was not baked by ParallelCluster",
            ),
            ClusterCreationFailure(
                "OnNodeConfiguredExecutionFailure",
                "Failed to execute OnNodeConfigured script.",
                "Failed to execute OnNodeConfigured script",
            ),
            ClusterCreationFailure(
                "OnNodeConfiguredDownloadFailure",
                "Failed to download OnNodeConfigured script.",
                "Failed to download OnNodeConfigured script",
            ),  # s3 and wget
            ClusterCreationFailure(
                "OnNodeConfiguredFailure",
                "Failed to run OnNodeConfigured script.",
                "Failed to run OnNodeConfigured script",
            ),
            ClusterCreationFailure(
                "OnNodeStartExecutionFailure",
                "Failed to execute OnNodeStart script.",
                "Failed to execute OnNodeStart script",
            ),
            ClusterCreationFailure(
                "OnNodeStartDownloadFailure",
                "Failed to download OnNodeStart script.",
                "Failed to download OnNodeStart script",
            ),  # s3 and wget
            ClusterCreationFailure(
                "OnNodeStartFailure", "Failed to run OnNodeStart script.", "Failed to run OnNodeStart script"
            ),
            ClusterCreationFailure("EbsMountFailure", "Failed to mount EBS volume.", "Failed to mount EBS volume"),
            ClusterCreationFailure("EfsMountFailure", "Failed to mount EFS.", "Failed to mount EFS"),
            ClusterCreationFailure("FsxMountFailure", "Failed to mount FSX.", "Failed to mount FSX"),
            ClusterCreationFailure("RaidMountFailure", "Failed to mount RAID array.", "Failed to mount RAID array"),
            ClusterCreationFailure(
                "HeadNodeBootstrapFailure", "Failed to set up the head node.", "Failed to run chef recipe"
            ),
            ClusterCreationFailure(
                "HeadNodeBootstrapFailure", "Failed to bootstrap the head node.", "Failed to bootstrap the head node"
            ),
            ClusterCreationFailure(
                "ResourceCreationFailure",
                "Failed to create resources for head node bootstrap.",
                "Resource creation cancelled",
            ),
            ClusterCreationFailure(
                "HeadNodeBootstrapFailure", "Cluster creation timed out.", "WaitCondition timed out"
            ),
            ClusterCreationFailure(
                "StaticNodeBootstrapFailure",
                "Cluster has been set to PROTECTED mode due to failures detected in static node provisioning.",
                "Cluster has been set to PROTECTED mode due to failures detected in static node provisioning",
            ),
        ]

        general_failure = failure = ClusterCreationFailure(
            "ClusterCreationFailure", "Failed to create the cluster.", ""
        )
        cfn_failure_reason = self._get_failure_reason()
        if cfn_failure_reason:
            failure = next(
                (f for f in cluster_creation_failures if f.cfn_failure_reason in cfn_failure_reason), general_failure
            )
        return failure.failure_code, failure.api_failure_reason


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


class ClusterLogsFiltersParser:
    """Class to parse filters."""

    def __init__(self, head_node: ClusterInstance, filters: List[str] = None):
        self.filters_list = []
        # The following attributes are used to compose log_stream_prefix,
        # that is the only filter that can be used for export-logs task
        self._head_node = head_node
        self._private_dns_name = None
        self._node_type = None
        self._log_stream_prefix = None
        rexp = r"Name=([^=,]+),Values=([^= ]+)(?: |$)"

        def _filter_parse(filter_str):
            match = re.match(rexp, filter_str)
            return match.groups() if match else None

        if filters:
            self.filters_list = [_filter_parse(f) for f in filters]
            if not self.filters_list or not all(self.filters_list):
                raise FiltersParserError(f"Invalid filters {filters}. They must be in the form Name=...,Values=...")

        for name, values in self.filters_list:
            if "," in values:
                raise FiltersParserError(f"Filter {name} doesn't accept comma separated strings as value.")

            attr_name = f"_{name.replace('-', '_')}"
            if not hasattr(self, attr_name):
                raise FiltersParserError(f"Filter {name} not supported.")
            setattr(self, attr_name, values)

    @property
    def log_stream_prefix(self):
        """Get log stream prefix filter."""
        if not self._log_stream_prefix:
            if self._private_dns_name:
                self._log_stream_prefix = self._private_dns_name
            elif self._node_type:
                if self._head_node:
                    self._log_stream_prefix = self._head_node.private_dns_name_short
                else:
                    raise FiltersParserError("HeadNode instance not available. Node Type filter cannot be used.")
        return self._log_stream_prefix

    def validate(self):
        """Check filters consistency."""
        if self._node_type:
            if self._node_type != "HeadNode":
                raise FiltersParserError("The only accepted value for Node Type filter is 'HeadNode'.")
            if self._private_dns_name:
                raise FiltersParserError("Private DNS Name and Node Type filters cannot be set at the same time.")


class ExportClusterLogsFiltersParser(ClusterLogsFiltersParser):
    """Class to manage export cluster logs filters."""

    def __init__(
        self,
        head_node: ClusterInstance,
        log_group_name: str,
        start_time: datetime.datetime = None,
        end_time: datetime.datetime = None,
        filters: List[str] = None,
    ):
        super().__init__(head_node, filters)
        self.time_parser = LogGroupTimeFiltersParser(log_group_name, start_time, end_time)

    @property
    def start_time(self):
        """Get start time parameter."""
        return self.time_parser.start_time

    @property
    def end_time(self):
        """Get end time parameter."""
        return self.time_parser.end_time

    def validate(self):
        """Check filter consistency."""
        super().validate()
        self.time_parser.validate(log_stream_prefix=self.log_stream_prefix)


class ListClusterLogsFiltersParser(ClusterLogsFiltersParser):
    """Class to manage list cluster logs filters."""

    def __init__(self, head_node: ClusterInstance, log_group_name: str, filters: str = None):
        super().__init__(head_node, filters)
        self._log_group_name = log_group_name
