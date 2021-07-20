# Copyright 2013-2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
# FIXME
# pylint: disable=too-many-locals
# pylint: disable=too-many-branches
# pylint: disable=too-many-statements

import logging
import os
import sys
from builtins import str

from pcluster import utils
from pcluster.api.pcluster_api import ApiFailure, PclusterApi
from pcluster.aws.common import get_region
from pcluster.cli_commands.compute_fleet_status_manager import ComputeFleetStatus, ComputeFleetStatusManager
from pcluster.models.cluster import NodeType

LOGGER = logging.getLogger(__name__)


# pylint: disable=inconsistent-return-statements
def read_config_file(config_file, fail_on_config_file_absence=True):
    """
    Read the config file.

    :param config_file: The config file to parse
    :param fail_on_config_file_absence: set to true to raise SystemExit if config file doesn't exist
    """
    if config_file:
        default_config = False
    elif "AWS_PCLUSTER_CONFIG_FILE" in os.environ:
        config_file = os.environ["AWS_PCLUSTER_CONFIG_FILE"]
        default_config = False
    else:
        config_file = utils.default_config_file_path()
        default_config = True

    if not os.path.isfile(config_file):
        if fail_on_config_file_absence:
            error_message = "Configuration file {0} not found.".format(config_file)
            if default_config:
                error_message += (
                    "\nYou can execute the 'pcluster configure' command "
                    "or see https://docs.aws.amazon.com/parallelcluster/latest/ug/configuration.html"
                )
            utils.error(error_message)
        else:
            LOGGER.debug("Specified configuration file %s doesn't exist.", config_file)
    else:
        LOGGER.debug("Reading configuration file %s", config_file)
    try:
        with open(config_file) as conf_file:
            content = conf_file.read()
        return content
    except Exception as e:
        utils.error("Error reading configuration file {0}. Error: {1}".format(config_file, str(e)))


def _print_compute_fleet_status(cluster_name, scheduler):
    if scheduler == "slurm":
        status_manager = ComputeFleetStatusManager(cluster_name)
        compute_fleet_status = status_manager.get_status()
        if compute_fleet_status != ComputeFleetStatus.UNKNOWN:
            LOGGER.info("ComputeFleetStatus: %s", compute_fleet_status)


def print_stack_outputs(stack_outputs):
    """
    Print a limited set of the CloudFormation Stack outputs.

    :param stack_outputs: the stack outputs dictionary
    """
    whitelisted_outputs = [
        "ClusterUser",
        "HeadNodePrivateIP",
        "HeadNodePublicIP",
        "BatchCliRequirements",
        "BatchComputeEnvironmentArn",
        "BatchJobQueueArn",
        "BatchJobDefinitionArn",
        "BatchJobDefinitionMnpArn",
        "BatchUserRole",
    ]

    for output in stack_outputs:
        output_key = output.get("OutputKey")
        if output_key in whitelisted_outputs:
            LOGGER.info("%s: %s", output_key, output.get("OutputValue"))


def _colorize(stack_status, args):
    """
    Color the output, COMPLETE = green, FAILED = red, IN_PROGRESS = yellow.

    :param stack_status: stack status
    :param args: args
    :return: colorized status string
    """
    if args.color:
        end = "0m"
        status_to_color = {"COMPLETE": "0;32m", "FAILED": "0;31m", "IN_PROGRESS": "10;33m"}
        for status_label, status_color in status_to_color.items():
            if status_label in stack_status:
                return "\033[%s%s\033[%s" % (status_color, stack_status, end)
    return stack_status


def ssh(args, extra_args):
    # pylint: disable=import-outside-toplevel
    """
    Execute an SSH command to the head node instance, according to the [aliases] section if there.

    :param args: pcluster CLI args
    :param extra_args: pcluster CLI extra_args
    """
    try:
        try:
            from shlex import quote as cmd_quote
        except ImportError:
            from pipes import quote as cmd_quote

        result = PclusterApi().describe_cluster_instances(
            cluster_name=args.cluster_name, region=get_region(), node_type=NodeType.HEAD_NODE
        )
        if isinstance(result, list) and len(result) == 1:
            # build command
            cmd = "ssh {CFN_USER}@{HEAD_NODE_IP} {ARGS}".format(
                CFN_USER=result[0].user,
                HEAD_NODE_IP=result[0].public_ip_address or result[0].private_ip_address,
                ARGS=" ".join(cmd_quote(str(arg)) for arg in extra_args),
            )

            # run command
            log_message = "SSH command: {0}".format(cmd)
            if not args.dryrun:
                LOGGER.debug(log_message)
                # A nosec comment is appended to the following line in order to disable the B605 check.
                # This check is disabled for the following reasons:
                # - The args passed to the remote command are sanitized.
                # - The default command to which these args is known.
                # - Users have full control over any customization of the command to which args are passed.
                os.system(cmd)  # nosec nosemgrep
            else:
                LOGGER.info(log_message)
        else:
            utils.error(f"Unable to connect to the cluster {args.cluster_name}.\n{result.message}")

    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


def build_image(args):
    """Build AWS ParallelCluster AMI."""
    LOGGER.info("Building AWS ParallelCluster image. This could take a while...")
    try:
        response = PclusterApi().build_image(
            imagebuilder_config=read_config_file(args.config_file),
            image_id=args.id,
            region=get_region(),
        )

        if isinstance(response, ApiFailure):
            message = "Build image failed. {0}.".format(response.message if response.message else "")
            if response.validation_failures:
                message += "\nValidation failures:\n"
                message += "\n".join(
                    [f"{result.level.name}: {result.message}" for result in response.validation_failures]
                )
            utils.error(message)
        else:
            LOGGER.info("Build image started successfully.")
            LOGGER.info("Response:")
            LOGGER.info({"image": response.__repr__()})
    except Exception as e:
        utils.error(
            "Error parsing configuration file {0}.\nDouble check it's a valid Yaml file. "
            "Error: {1}".format(args.config_file, str(e))
        )
