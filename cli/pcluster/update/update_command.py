# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import time

import boto3
from botocore.exceptions import ClientError

import pcluster.utils as utils
from pcluster.config.config_patch import ConfigPatch
from pcluster.config.param_types import Updatability
from pcluster.config.pcluster_config import PclusterConfig

LOGGER = logging.getLogger(__name__)


def execute(args):
    LOGGER.info("Updating: %s", args.cluster_name)
    stack_name = utils.get_stack_name(args.cluster_name)
    target_config = PclusterConfig(
        config_file=args.config_file, cluster_label=args.cluster_template, fail_on_file_absence=True
    )
    target_config.validate()
    cfn_params = target_config.to_cfn()

    cluster_section = target_config.get_section("cluster")
    cfn = boto3.client("cloudformation")
    if cluster_section.get_param_value("scheduler") != "awsbatch":
        if not args.reset_desired:
            asg_name = utils.get_asg_name(stack_name)
            desired_capacity = (
                boto3.client("autoscaling")
                .describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
                .get("AutoScalingGroups")[0]
                .get("DesiredCapacity")
            )
            cfn_params["DesiredSize"] = str(desired_capacity)
    else:
        if args.reset_desired:
            LOGGER.info("reset_desired flag does not work with awsbatch scheduler")
        params = utils.get_stack(stack_name, cfn).get("Parameters")

        for parameter in params:
            if parameter.get("ParameterKey") == "ResourcesS3Bucket":
                cfn_params["ResourcesS3Bucket"] = parameter.get("ParameterValue")

    # Retrieving base config from cfn
    can_proceed = True
    base_config = PclusterConfig(config_file=args.config_file, cluster_name=args.cluster_name)
    try:
        patch = ConfigPatch(base_config, target_config)
        updatability = patch.updatability

        LOGGER.info("Found Changes:")
        if len(patch.changes):
            for change in patch.changes:
                LOGGER.info("{0}".format(change))
        else:
            LOGGER.info("No changes found in your cluster configuration. Update is not needed.")
            sys.exit(0)

        if updatability < Updatability.UNKNOWN:
            LOGGER.info("Congratulations! The new configuration can be safely applied to your cluster.")
            if updatability > Updatability.ALLOWED:
                LOGGER.warning("The following additional operations will be needed:")
                if updatability >= Updatability.COMPUTE_FLEET_RESTART:
                    LOGGER.warning("- Restart compute fleet.")
                if updatability == Updatability.MASTER_RESTART:
                    LOGGER.warning("- Restart master node.")
        else:
            LOGGER.error("The new configuration cannot be safely applied to your cluster.")
            LOGGER.error("Please check the report above for details.")
            can_proceed = False
    except Exception as e:
        LOGGER.error(e)
        can_proceed = False

    if can_proceed:
        user_input = input("Do you want to proceed? - Y/N").strip().lower()
        if user_input != "y":
            can_proceed = False

    if not can_proceed:
        sys.exit(1)

    try:
        LOGGER.debug(cfn_params)
        if args.extra_parameters:
            LOGGER.debug("Adding extra parameters to the CFN parameters")
            cfn_params.update(dict(args.extra_parameters))

        cfn_params = [{"ParameterKey": key, "ParameterValue": value} for key, value in cfn_params.items()]
        LOGGER.info("Calling update_stack")
        cfn.update_stack(
            StackName=stack_name, UsePreviousTemplate=True, Parameters=cfn_params, Capabilities=["CAPABILITY_IAM"]
        )
        stack_status = utils.get_stack(stack_name, cfn).get("StackStatus")
        if not args.nowait:
            while stack_status == "UPDATE_IN_PROGRESS":
                stack_status = utils.get_stack(stack_name, cfn).get("StackStatus")
                events = cfn.describe_stack_events(StackName=stack_name).get("StackEvents")[0]
                resource_status = (
                    "Status: %s - %s" % (events.get("LogicalResourceId"), events.get("ResourceStatus"))
                ).ljust(80)
                sys.stdout.write("\r%s" % resource_status)
                sys.stdout.flush()
                time.sleep(5)
        else:
            stack_status = utils.get_stack(stack_name, cfn).get("StackStatus")
            LOGGER.info("Status: %s", stack_status)
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)
