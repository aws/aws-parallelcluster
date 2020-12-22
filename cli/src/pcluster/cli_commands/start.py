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
import abc
import logging
import sys
from abc import abstractmethod

import boto3
from botocore.exceptions import ClientError

from pcluster import utils
from pcluster.cli_commands.compute_fleet_status_manager import ComputeFleetStatus, ComputeFleetStatusManager
from pcluster.config.pcluster_config import PclusterConfig
from pcluster.utils import error

if sys.version_info >= (3, 4):
    ABC = abc.ABC
else:
    ABC = abc.ABCMeta("ABC", (), {})

LOGGER = logging.getLogger(__name__)


def start(args):
    """Start cluster compute fleet."""
    pcluster_config = PclusterConfig(
        config_file=args.config_file,
        cluster_name=args.cluster_name,
        auto_refresh=False,
        enforce_version=False,
        skip_load_json_config=True,
    )
    pcluster_config.cluster_model.get_start_command(pcluster_config).start(args, pcluster_config)


class StartCommand(ABC):
    """Interface to implement start command."""

    @abstractmethod
    def start(self, args, pcluster_config):
        """Start the compute fleet."""
        pass


class AWSBatchStartCommand(StartCommand):
    """Start command for the AWSBatch cluster."""

    def start(self, args, pcluster_config):
        """Start the compute fleet."""
        LOGGER.info("Enabling AWS Batch compute environment : %s", args.cluster_name)
        stack_name = utils.get_stack_name(args.cluster_name)
        cluster_section = pcluster_config.get_section("cluster")
        max_vcpus = cluster_section.get_param_value("max_vcpus")
        desired_vcpus = cluster_section.get_param_value("desired_vcpus")
        min_vcpus = cluster_section.get_param_value("min_vcpus")
        ce_name = utils.get_batch_ce(stack_name)
        self._start_batch_ce(ce_name=ce_name, min_vcpus=min_vcpus, desired_vcpus=desired_vcpus, max_vcpus=max_vcpus)

    @staticmethod
    def _start_batch_ce(ce_name, min_vcpus, desired_vcpus, max_vcpus):
        try:
            boto3.client("batch").update_compute_environment(
                computeEnvironment=ce_name,
                state="ENABLED",
                computeResources={
                    "minvCpus": int(min_vcpus),
                    "maxvCpus": int(max_vcpus),
                    "desiredvCpus": int(desired_vcpus),
                },
            )
        except ClientError as e:
            LOGGER.critical(e.response.get("Error").get("Message"))
            sys.exit(1)


class SITStartCommand(StartCommand):
    """Start command for the ASG based clusters."""

    def start(self, args, pcluster_config):
        """Start the compute fleet."""
        LOGGER.info("Starting compute fleet: %s", args.cluster_name)
        cluster_section = pcluster_config.get_section("cluster")
        stack_name = utils.get_stack_name(args.cluster_name)
        max_queue_size = cluster_section.get_param_value("max_queue_size")
        min_desired_size = (
            cluster_section.get_param_value("initial_queue_size")
            if cluster_section.get_param_value("maintain_initial_size")
            else 0
        )
        asg_name = utils.get_asg_name(stack_name)
        utils.set_asg_limits(asg_name=asg_name, min=min_desired_size, max=max_queue_size, desired=min_desired_size)


class HITStartCommand(StartCommand):
    """Start command for the HIT based clusters."""

    def start(self, args, pcluster_config):
        """Start the compute fleet."""
        stack_status = pcluster_config.cfn_stack.get("StackStatus")
        if "IN_PROGRESS" in stack_status:
            error("Cannot start compute fleet while stack is in {} status.".format(stack_status))
        elif "FAILED" in stack_status:
            LOGGER.warning("Cluster stack is in %s status. This operation might fail.", stack_status)

        try:
            compute_fleet_status_manager = ComputeFleetStatusManager(args.cluster_name)
            compute_fleet_status_manager.update_status(
                ComputeFleetStatus.START_REQUESTED, ComputeFleetStatus.STARTING, ComputeFleetStatus.RUNNING
            )
        except ComputeFleetStatusManager.ConditionalStatusUpdateFailed:
            error(
                "Failed when starting compute fleet due to a concurrent update of the status. "
                "Please retry the operation."
            )
        except Exception as e:
            error("Failed when starting compute fleet with error: {}".format(e))
