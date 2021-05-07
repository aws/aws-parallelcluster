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
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.aws_resources import InstanceInfo, StackInfo
from pcluster.constants import OS_MAPPING, PCLUSTER_S3_BUCKET_TAG, PCLUSTER_S3_CLUSTER_DIR_TAG, PCLUSTER_STACK_PREFIX


class ClusterStack(StackInfo):
    """Class representing a running stack associated to a Cluster."""

    def __init__(self, stack_data: dict):
        """Init stack info."""
        super().__init__(stack_data)

    @property
    def cluster_name(self):
        """Return cluster name associated to this cluster."""
        return self.name[len(PCLUSTER_STACK_PREFIX) :]  # noqa: E203

    @property
    def version(self):
        """Return the version of ParallelCluster used to create the stack."""
        return self.get_tag("Version")

    @property
    def s3_bucket_name(self):
        """Return the name of the bucket used to store cluster information."""
        return self.get_tag(PCLUSTER_S3_BUCKET_TAG)

    @property
    def s3_artifact_directory(self):
        """Return the artifact directory of the bucket used to store cluster information."""
        return self.get_tag(PCLUSTER_S3_CLUSTER_DIR_TAG)

    @property
    def head_node_user(self):
        """Return the output storing cluster user."""
        return self._get_output("ClusterUser")

    @property
    def head_node_ip(self):
        """Return the IP to be used to connect to the head node, public or private."""
        return self._get_output("HeadNodePublicIP") or self._get_output("HeadNodePrivateIP")

    @property
    def scheduler(self):
        """Return the scheduler used in the cluster."""
        return self._get_output("Scheduler")

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
        return self._get_tag("parallelcluster:node-type")

    def _get_tag(self, tag_key: str):
        return next(iter([tag["Value"] for tag in self._tags if tag["Key"] == tag_key]), None)
