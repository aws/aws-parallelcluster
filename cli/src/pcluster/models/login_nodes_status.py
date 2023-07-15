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
from enum import Enum

from pcluster.aws.aws_api import AWSApi
from pcluster.utils import get_chunks

LOGGER = logging.getLogger(__name__)


class LoginNodesPoolState(Enum):
    """Represents the internal status of the login nodes pools."""

    PENDING = "pending"
    ACTIVE = "active"
    FAILED = "failed"

    def __str__(self):
        return str(self.value)


class LoginNodesStatus:
    """Represents the status of the cluster login nodes pools."""

    def __init__(self, stack_name):
        self._stack_name = stack_name
        self._login_nodes_pool_name = None
        self._login_nodes_pool_available = False
        self._load_balancer_arn = None
        self._target_group_arn = None
        self._status = None
        self._dns_name = None
        self._scheme = None
        self._healthy_nodes = None
        self._unhealthy_nodes = None

    def __str__(self):
        return (
            f'("status": "{self._status}", "address": "{self._dns_name}", "scheme": "{self._scheme}", '
            f'"healthyNodes": "{self._healthy_nodes}", "unhealthy_nodes": "{self._unhealthy_nodes}")'
        )

    def get_login_nodes_pool_available(self):
        """Return the status of a login nodes fleet."""
        return self._login_nodes_pool_available

    def get_status(self):
        """Return the status of a login nodes fleet."""
        return self._status

    def get_address(self):
        """Return the single connection address of a login nodes fleet."""
        return self._dns_name

    def get_scheme(self):
        """Return the schema of a login nodes fleet."""
        return self._scheme

    def get_healthy_nodes(self):
        """Return the number of healthy nodes of a login nodes fleet."""
        return self._healthy_nodes

    def get_unhealthy_nodes(self):
        """Return the number of unhealthy nodes of a login nodes fleet."""
        return self._unhealthy_nodes

    def retrieve_data(self, login_nodes_pool_name):
        """Initialize the class with the information related to the login nodes pool."""
        self._login_nodes_pool_name = login_nodes_pool_name
        self._retrieve_assigned_load_balancer()
        if self._load_balancer_arn:
            self._login_nodes_pool_available = True
            self._populate_target_groups()
            self._populate_target_group_health()

    def _retrieve_assigned_load_balancer(self):
        load_balancers = AWSApi.instance().elb.list_load_balancers()
        tags_list = self._retrieve_all_tags([o.get("LoadBalancerArn") for o in load_balancers])
        self._load_balancer_arn_from_tags(tags_list)
        if self._load_balancer_arn:
            for load_balancer in load_balancers:
                if load_balancer.get("LoadBalancerArn") == self._load_balancer_arn:
                    self._map_status(load_balancer.get("State").get("Code"))
                    self._dns_name = load_balancer.get("DNSName")
                    self._scheme = load_balancer.get("Scheme")
                    break

    def _load_balancer_arn_from_tags(self, tags_list):
        for tags in tags_list:
            if self._key_value_tag_found(
                tags, "parallelcluster:cluster-name", self._stack_name
            ) and self._key_value_tag_found(tags, "parallelcluster:login-nodes-pool", self._login_nodes_pool_name):
                self._load_balancer_arn = tags.get("ResourceArn")
                break

    def _key_value_tag_found(self, tags, key, value):
        if any(key == kv.get("Key") and kv.get("Value") == value for kv in tags.get("Tags")):
            return True
        return False

    def _retrieve_all_tags(self, load_balancers):
        tags = []
        if len(load_balancers) > 0:
            chunks = get_chunks(load_balancers)
            for chunk in chunks:
                tags.extend(AWSApi.instance().elb.describe_tags(chunk))
        return tags

    def _map_status(self, load_balancer_state):
        if load_balancer_state == "provisioning":
            self._status = LoginNodesPoolState.PENDING
        elif load_balancer_state == "active":
            self._status = LoginNodesPoolState.ACTIVE
        else:
            self._status = LoginNodesPoolState.FAILED

    def _populate_target_groups(self):
        if self._status is LoginNodesPoolState.ACTIVE:
            try:
                target_groups = AWSApi.instance().elb.describe_target_groups(self._load_balancer_arn)
                if target_groups:
                    self._target_group_arn = target_groups[0].get("TargetGroupArn")
            except Exception as e:
                LOGGER.warning(
                    "Failed when retrieving target_groups with error %s. "
                    "This is expected if login nodes pool creation/deletion is in progress",
                    e,
                )

    def _populate_target_group_health(self):
        if self._target_group_arn:
            try:
                target_group_healths = AWSApi.instance().elb.describe_target_health(self._target_group_arn)
                healthy_target = [
                    target_health.get("Target").get("Id")
                    for target_health in target_group_healths
                    if target_health.get("TargetHealth").get("State") == "healthy"
                ]
                self._healthy_nodes = len(healthy_target)
                self._unhealthy_nodes = len(target_group_healths) - len(healthy_target)
            except Exception as e:
                LOGGER.warning(
                    "Failed when retrieving information on the target group health with error %s. "
                    "This is expected if login nodes pool creation/deletion is in progress",
                    e,
                )
