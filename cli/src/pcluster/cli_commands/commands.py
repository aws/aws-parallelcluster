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

from botocore.exceptions import ClientError
from tabulate import tabulate

from pcluster import utils
from pcluster.api.pcluster_api import ApiFailure, ClusterInfo, ImageBuilderInfo, PclusterApi
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


def create(args):
    """Create cluster."""
    LOGGER.info("Beginning cluster creation for cluster: %s", args.cluster_name)
    LOGGER.debug("CLI args: %s", str(args))

    try:
        if not args.disable_update_check:
            utils.check_if_latest_version()

        cluster_config = read_config_file(config_file=args.config_file)
        result = PclusterApi().create_cluster(
            cluster_config=cluster_config,
            cluster_name=args.cluster_name,
            region=get_region(),
            disable_rollback=args.norollback,
            suppress_validators=args.suppress_validators,
            validation_failure_level=args.validation_failure_level,
        )
        if isinstance(result, ClusterInfo):
            print("Cluster creation started successfully.")

            if not args.nowait:
                verified = utils.verify_stack_status(
                    result.stack_name, waiting_states=["CREATE_IN_PROGRESS"], successful_states=["CREATE_COMPLETE"]
                )
                if not verified:
                    LOGGER.critical("\nCluster creation failed. Failed events:")
                    utils.log_stack_failure_recursive(result.stack_name)
                    sys.exit(1)

                LOGGER.info("")
                result = PclusterApi().describe_cluster(cluster_name=args.cluster_name, region=get_region())
                if isinstance(result, ClusterInfo):
                    print_stack_outputs(result.stack_outputs)
                else:
                    utils.error(f"Unable to retrieve the status of the cluster.\n{result.message}")
            else:
                LOGGER.info("Status: %s", result.stack_status)
        else:
            message = "Cluster creation failed. {0}.".format(result.message if result.message else "")
            if result.validation_failures:
                message += "\nValidation failures:\n"
                message += "\n".join(
                    [f"{result.level.name}: {result.message}" for result in result.validation_failures]
                )

            utils.error(message)

    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


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


def list_clusters(args):
    """List existing clusters."""
    try:
        result = PclusterApi().list_clusters(region=get_region())
        if isinstance(result, list):
            clusters = [[cluster.name, _colorize(cluster.status, args), cluster.version] for cluster in result]
            LOGGER.info(tabulate(clusters, tablefmt="plain"))
        else:
            utils.error(f"Unable to retrieve the list of clusters.\n{result.message}")
    except KeyboardInterrupt:
        LOGGER.info("Exiting...")
        sys.exit(0)


def instances(args):
    """Print the list of instances associated to the cluster."""
    try:
        result = PclusterApi().describe_cluster_instances(cluster_name=args.cluster_name, region=get_region())
        if isinstance(result, list):
            for instance in result:
                LOGGER.info("%s         %s", f"{instance.node_type}\t", instance.instance_id)
        else:
            utils.error(f"Unable to retrieve the instances of the cluster.\n{result.message}")
    except KeyboardInterrupt:
        LOGGER.info("Exiting...")
        sys.exit(0)


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


def status(args):
    """Get cluster status."""
    try:
        result = PclusterApi().describe_cluster(cluster_name=args.cluster_name, region=get_region())
        if isinstance(result, ClusterInfo):
            sys.stdout.write(f"\rStatus: {result.stack_status}\n")
            sys.stdout.flush()
            if not args.nowait:
                verified = utils.verify_stack_status(
                    result.stack_name,
                    waiting_states=[
                        "CREATE_IN_PROGRESS",
                        "ROLLBACK_IN_PROGRESS",
                        "UPDATE_IN_PROGRESS",
                        "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
                        "UPDATE_ROLLBACK_IN_PROGRESS",
                        "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS",
                        "REVIEW_IN_PROGRESS",
                        "IMPORT_IN_PROGRESS",
                        "IMPORT_ROLLBACK_IN_PROGRESS",
                        "DELETE_IN_PROGRESS",
                    ],
                    successful_states=["CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"],
                )
                if verified:
                    _print_cluster_status(args.cluster_name, result.scheduler)
                else:
                    # Log failed events
                    utils.log_stack_failure_recursive(
                        result.stack_name, failed_states=["CREATE_FAILED", "DELETE_FAILED", "UPDATE_FAILED"]
                    )
            else:
                sys.stdout.write("\n")
                sys.stdout.flush()

        else:
            utils.error(f"Unable to retrieve the status of the cluster.\n{result.message}")

    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


def _print_cluster_status(cluster_name, scheduler):
    """Print head node and compute fleet status."""
    result = PclusterApi().describe_cluster_instances(
        cluster_name=cluster_name, region=get_region(), node_type=NodeType.HEAD_NODE
    )
    if isinstance(result, list):
        if len(result) == 1:
            LOGGER.info("%s: %s", result[0].node_type, result[0].state)
            _print_compute_fleet_status(cluster_name, scheduler)
        else:
            utils.error("Unexpected error. Unable to retrieve Head Node information")
    else:
        utils.error(f"Unable to retrieve the status of the cluster's instances.\n{result.message}")


def delete(args):  # noqa: C901
    """Delete cluster described by cluster_name."""
    LOGGER.info("Deleting: %s", args.cluster_name)
    LOGGER.debug("CLI args: %s", str(args))
    try:
        # delete cluster raises an exception if stack does not exist
        result = PclusterApi().delete_cluster(args.cluster_name, get_region(), args.keep_logs)
        if isinstance(result, ClusterInfo):
            print("Cluster deletion started correctly.")
        else:
            utils.error(f"Cluster deletion failed. {result.message}")

        sys.stdout.write("\rStatus: %s" % result.stack_status)
        sys.stdout.flush()
        LOGGER.debug("Status: %s", result.stack_status)
        if not args.nowait:
            verified = utils.verify_stack_status(
                result.stack_arn, waiting_states=["DELETE_IN_PROGRESS"], successful_states=["DELETE_COMPLETE"]
            )
            if not verified:
                result = PclusterApi().describe_cluster(cluster_name=args.cluster_name, region=get_region())
                if isinstance(result, ClusterInfo):
                    utils.log_stack_failure_recursive(result.stack_arn, failed_states=["DELETE_FAILED"])
                elif isinstance(result, ApiFailure):
                    # If stack is already deleted
                    if f"Cluster {args.cluster_name} doesn't exist." in result.message:
                        LOGGER.warning("\nCluster %s has already been deleted or does not exist.", args.cluster_name)
                        sys.exit(0)
                    LOGGER.critical(result.message)
                    sys.stdout.flush()
                    sys.exit(1)
                else:
                    utils.error(f"Unable to retrieve the status of the cluster.\n{result.message}")

            sys.stdout.write("\rStatus: %s\n" % result.stack_status)
            sys.stdout.flush()
            LOGGER.debug("Status: %s", result.stack_status)
        else:
            sys.stdout.write("\n")
            sys.stdout.flush()
        if result.stack_status == "DELETE_FAILED":
            LOGGER.info("Cluster did not delete successfully. Run 'pcluster delete %s' again", args.cluster_name)
    except ClientError as e:
        if e.response.get("Error").get("Message").endswith("doesn't exist"):
            LOGGER.warning("\nCluster %s has already been deleted or does not exist.", args.cluster_name)
            sys.exit(0)
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.stdout.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


def start(args):
    """Start cluster compute fleet."""
    try:
        result = PclusterApi().update_compute_fleet_status(
            cluster_name=args.cluster_name,
            region=get_region(),
            status=ComputeFleetStatus.START_REQUESTED,
        )
        if isinstance(result, ApiFailure):
            utils.error(f"Unable to start the compute fleet of the cluster.\n{result.message}")
        else:
            LOGGER.info("Compute fleet started correctly.")
    except KeyboardInterrupt:
        LOGGER.info("Exiting...")
        sys.exit(0)


def stop(args):
    """Stop cluster compute fleet."""
    try:
        result = PclusterApi().update_compute_fleet_status(
            cluster_name=args.cluster_name,
            region=get_region(),
            status=ComputeFleetStatus.STOP_REQUESTED,
        )
        if isinstance(result, ApiFailure):
            utils.error(f"Unable to stop the compute fleet of the cluster.\n{result.message}")
        else:
            LOGGER.info("Compute fleet stopped correctly.")
    except KeyboardInterrupt:
        LOGGER.info("Exiting...")
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


def update(args):
    """Update cluster."""
    LOGGER.info("Beginning update of cluster: %s", args.cluster_name)
    LOGGER.debug("CLI args: %s", str(args))

    try:
        cluster_config = read_config_file(config_file=args.config_file)
        # delete cluster raises an exception if stack does not exist
        result = PclusterApi().update_cluster(cluster_config, args.cluster_name, get_region())
        if isinstance(result, ClusterInfo):
            print("Cluster update started correctly.")
        else:
            utils.error(f"Cluster update failed. {result.message}")
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


def delete_image(args):
    """Delete image described by image_name."""
    LOGGER.info("Deleting: %s", args.id)
    LOGGER.debug("CLI args: %s", str(args))
    try:
        # delete image raises an exception if stack does not exist
        result = PclusterApi().delete_image(image_id=args.id, region=get_region(), force=args.force)
        if isinstance(result, ImageBuilderInfo):
            result.imagebuild_status = "DELETE_IN_PROGRESS"

            print(f"Image deletion started correctly. {result}")
        else:
            utils.error(f"Image deletion failed. {result.message}")

        if result.stack_exist:
            sys.stdout.write("\rImageBuilderStackStatus: %s" % result.stack_status)
            sys.stdout.flush()
            LOGGER.debug("ImageBuilderStackStatus: %s", result.stack_status)

        else:
            sys.stdout.write("\rImageStatus: %s" % result.image_state)
            sys.stdout.flush()
            LOGGER.debug("ImageStatus: %s", result.image_state)

        sys.stdout.write("\n")
        sys.stdout.flush()
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


def describe_image(args):
    """Describe image info by image_name."""
    try:
        result = PclusterApi().describe_image(image_id=args.id, region=get_region())
        LOGGER.info("Response:")
        if isinstance(result, ApiFailure):
            LOGGER.info("Build image error %s", result.message)
        else:
            LOGGER.info({"image": result.__repr__()})
    except KeyboardInterrupt:
        LOGGER.info("Exiting...")
        sys.exit(0)


def list_images(args):
    """List existing AWS ParallelCluster AMIs."""
    try:
        result = PclusterApi().list_images(region=get_region())
        if isinstance(result, list):
            images = []
            for info in result:
                if info.stack_exist:
                    name = info.stack_name
                    imagebuild_status = info.imagebuild_status
                else:
                    name = info.image_id
                    imagebuild_status = "BUILD_COMPLETE"
                images.append([name, _colorize(imagebuild_status, args), info.version])
            LOGGER.info(tabulate(images, tablefmt="plain"))
        else:
            utils.error(f"Unable to retrieve the list of images.\n{result.message}")
    except KeyboardInterrupt:
        LOGGER.info("Exiting...")
        sys.exit(0)
