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

import boto3

from pcluster import utils
from pcluster.config.pcluster_config import PclusterConfig

LOGGER = logging.getLogger(__name__)


def stop(args):
    """Set ASG limits or awsbatch ce to min/max/desired = 0/0/0."""
    stack_name = utils.get_stack_name(args.cluster_name)
    pcluster_config = PclusterConfig(config_file=args.config_file, cluster_name=args.cluster_name, auto_refresh=False)
    cluster_section = pcluster_config.get_section("cluster")

    if cluster_section.get_param_value("scheduler") == "awsbatch":
        LOGGER.info("Disabling AWS Batch compute environment : %s", args.cluster_name)
        ce_name = utils.get_batch_ce(stack_name)
        _stop_batch_ce(ce_name=ce_name)
    elif cluster_section.get_param_value("scheduler") == "slurm":
        # TODO: to be implemented
        raise NotImplementedError()
    else:
        LOGGER.info("Stopping compute fleet: %s", args.cluster_name)
        asg_name = utils.get_asg_name(stack_name)
        utils.set_asg_limits(asg_name=asg_name, min=0, max=0, desired=0)


def _stop_batch_ce(ce_name):
    boto3.client("batch").update_compute_environment(computeEnvironment=ce_name, state="DISABLED")
