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

import boto3

from pcluster import utils
from pcluster.cli_commands.compute_fleet_status_manager import ComputeFleetStatus, ComputeFleetStatusManager
from pcluster.config.pcluster_config import PclusterConfig
from pcluster.utils import error

if sys.version_info >= (3, 4):
    ABC = abc.ABC
else:
    ABC = abc.ABCMeta("ABC", (), {})

LOGGER = logging.getLogger(__name__)


def stop(args):
    """Stop cluster compute fleet."""
    pcluster_config = PclusterConfig(
        config_file=args.config_file,
        cluster_name=args.cluster_name,
        auto_refresh=False,
        enforce_version=False,
        skip_load_json_config=True,
    )
    pcluster_config.cluster_model.get_stop_command(pcluster_config).stop(args, pcluster_config)


class StopCommand(ABC):
    """Interface to implement stop command."""

    @abc.abstractmethod
    def stop(self, args, pcluster_config):
        """Stop the compute fleet."""
        pass


class AWSBatchStopCommand(StopCommand):
    """Stop command for the AWSBatch cluster."""

    def stop(self, args, pcluster_config):
        """Stop the compute fleet."""
        LOGGER.info("Disabling AWS Batch compute environment : %s", args.cluster_name)
        stack_name = utils.get_stack_name(args.cluster_name)
        ce_name = utils.get_batch_ce(stack_name)
        self._stop_batch_ce(ce_name=ce_name)

    @staticmethod
    def _stop_batch_ce(ce_name):
        boto3.client("batch").update_compute_environment(computeEnvironment=ce_name, state="DISABLED")


class SITStopCommand(StopCommand):
    """Stop command for the ASG based clusters."""

    def stop(self, args, pcluster_config):
        """Stop the compute fleet."""
        LOGGER.info("Stopping compute fleet: %s", args.cluster_name)
        stack_name = utils.get_stack_name(args.cluster_name)
        asg_name = utils.get_asg_name(stack_name)
        utils.set_asg_limits(asg_name=asg_name, min=0, max=0, desired=0)


class HITStopCommand(StopCommand):
    """Stop command for the HIT based clusters."""

    def stop(self, args, pcluster_config):
        """Stop the compute fleet."""
        stack_status = pcluster_config.cfn_stack.get("StackStatus")
        if "IN_PROGRESS" in stack_status:
            error("Cannot stop compute fleet while stack is in {} status.".format(stack_status))
        elif "FAILED" in stack_status:
            LOGGER.warning("Cluster stack is in %s status. This operation might fail.", stack_status)

        try:
            compute_fleet_status_manager = ComputeFleetStatusManager(args.cluster_name)
            compute_fleet_status_manager.update_status(
                ComputeFleetStatus.STOP_REQUESTED, ComputeFleetStatus.STOPPING, ComputeFleetStatus.STOPPED
            )
        except ComputeFleetStatusManager.ConditionalStatusUpdateFailed:
            error(
                "Failed when stopping compute fleet due to a concurrent update of the status. "
                "Please retry the operation."
            )
        except Exception as e:
            error("Failed when stopping compute fleet with error: {}".format(e))
