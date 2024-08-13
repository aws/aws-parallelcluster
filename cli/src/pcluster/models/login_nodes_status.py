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


class PoolStatus:
    """Represents the status of a pool of login nodes."""

    def __init__(self, stack_name, pool_name):
        self._dns_name = None
        self._status = None
        self._scheme = None
        self._pool_name = pool_name
        self._pool_available = False
        self._stack_name = stack_name
        self._healthy_nodes = None
        self._unhealthy_nodes = None
        self._load_balancer_arn = None
        self._target_group_arn = None
        self._retrieve_data()

    def __str__(self):
        return (
            f'("status": "{self._status}", "address": "{self._dns_name}", "scheme": "{self._scheme}", '
            f'"healthy_nodes": "{self._healthy_nodes}", "unhealthy_nodes": "{self._unhealthy_nodes}"),'
        )

    def get_healthy_nodes(self):
        """Return the number of healthy nodes of the login node pool."""
        return self._healthy_nodes

    def get_unhealthy_nodes(self):
        """Return the number of unhealthy nodes of the login node pool."""
        return self._unhealthy_nodes

    def get_pool_available(self):
        """Return true if the pool is available."""
        return self._pool_available

    def get_status(self):
        """Return the status of the login node pool."""
        return self._status

    def get_address(self):
        """Return the connection addresses of the login node pool."""
        return self._dns_name

    def get_scheme(self):
        """Return the schema of the login node pool."""
        return self._scheme

    def _retrieve_data(self):
        """Initialize the class with the information related to the login nodes pool."""
        self._retrieve_assigned_load_balancer()
        if self._load_balancer_arn:
            self._pool_available = True
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
            ) and self._key_value_tag_found(tags, "parallelcluster:login-nodes-pool", self._pool_name):
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


class LoginNodesStatus:
    """Represents the status of the cluster login nodes pools."""

    def __init__(self, stack_name):
        self._stack_name = stack_name
        self._pool_status_dict = dict()
        self._login_nodes_pool_available = False
        self._total_healthy_nodes = None
        self._total_unhealthy_nodes = None

    def __str__(self):
        out = ""
        for pool_status in self._pool_status_dict.values():
            out += str(pool_status)
        return out

    def get_login_nodes_pool_available(self):
        """Return true if a pool is available in the login nodes fleet."""
        return self._login_nodes_pool_available

    def get_pool_status_dict(self):
        """Return a dictionary mapping each login node pool name to respective pool status."""
        return self._pool_status_dict

    def get_healthy_nodes(self, pool_name=None):
        """Return the total number of healthy login nodes in the cluster or a specific pool."""
        healthy_nodes = (
            self._pool_status_dict.get(pool_name).get_healthy_nodes() if pool_name else self._total_healthy_nodes
        )
        return healthy_nodes

    def get_unhealthy_nodes(self, pool_name=None):
        """Return the total number of unhealthy login nodes in the cluster or a specific pool."""
        unhealthy_nodes = (
            self._pool_status_dict.get(pool_name).get_unhealthy_nodes() if pool_name else self._total_unhealthy_nodes
        )
        return unhealthy_nodes

    def retrieve_data(self, login_node_pool_names):
        """Initialize the class with the information related to the login node fleet."""
        for pool_name in login_node_pool_names:
            self._pool_status_dict[pool_name] = PoolStatus(self._stack_name, pool_name)
        self._total_healthy_nodes = sum(
            (
                pool_status.get_healthy_nodes()
                for pool_status in self._pool_status_dict.values()
                if pool_status.get_healthy_nodes()
            )
        )
        self._total_unhealthy_nodes = sum(
            (
                pool_status.get_unhealthy_nodes()
                for pool_status in self._pool_status_dict.values()
                if pool_status.get_unhealthy_nodes()
            )
        )
        self._login_nodes_pool_available = any(
            (pool_status.get_pool_available() for pool_status in self._pool_status_dict.values())
        )
