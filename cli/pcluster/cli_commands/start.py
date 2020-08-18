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
import sys

import boto3
from botocore.exceptions import ClientError

from pcluster import utils
from pcluster.config.pcluster_config import PclusterConfig

LOGGER = logging.getLogger(__name__)


def start(args):
    """Restore ASG limits or awsbatch CE to min/max/desired."""
    stack_name = utils.get_stack_name(args.cluster_name)
    pcluster_config = PclusterConfig(config_file=args.config_file, cluster_name=args.cluster_name, auto_refresh=False)
    cluster_section = pcluster_config.get_section("cluster")

    if cluster_section.get_param_value("scheduler") == "awsbatch":
        LOGGER.info("Enabling AWS Batch compute environment : %s", args.cluster_name)
        max_vcpus = cluster_section.get_param_value("max_vcpus")
        desired_vcpus = cluster_section.get_param_value("desired_vcpus")
        min_vcpus = cluster_section.get_param_value("min_vcpus")
        ce_name = utils.get_batch_ce(stack_name)
        _start_batch_ce(ce_name=ce_name, min_vcpus=min_vcpus, desired_vcpus=desired_vcpus, max_vcpus=max_vcpus)
    elif cluster_section.get_param_value("scheduler") == "slurm":
        # TODO: to be implemented
        raise NotImplementedError()
    else:
        LOGGER.info("Starting compute fleet: %s", args.cluster_name)
        max_queue_size = cluster_section.get_param_value("max_queue_size")
        min_desired_size = (
            cluster_section.get_param_value("initial_queue_size")
            if cluster_section.get_param_value("maintain_initial_size")
            else 0
        )
        asg_name = utils.get_asg_name(stack_name)
        utils.set_asg_limits(asg_name=asg_name, min=min_desired_size, max=max_queue_size, desired=min_desired_size)


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
