# Copyright 2013-2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import time
from builtins import str

from tabulate import tabulate

import pcluster.utils as utils
from api.pcluster_api import ApiFailure, ClusterInfo, PclusterApi
from common.utils import load_yaml_dict
from pcluster.cli_commands.compute_fleet_status_manager import ComputeFleetStatus, ComputeFleetStatusManager

LOGGER = logging.getLogger(__name__)


def version():
    return utils.get_installed_version()


def _parse_config_file(config_file, fail_on_config_file_absence=True):
    """
    Parse the config file and initialize config_file and config_parser attributes.

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
        LOGGER.debug("Parsing configuration file %s", config_file)
    try:
        return load_yaml_dict(file_path=config_file)
    except Exception as e:
        utils.error(
            "Error parsing configuration file {0}.\nDouble check it's a valid Yaml file. "
            "Error: {1}".format(config_file, str(e))
        )


def create(args):
    """Create cluster."""
    LOGGER.info("Beginning cluster creation for cluster: %s", args.cluster_name)
    LOGGER.debug("CLI args: %s", str(args))

    try:
        if not args.disable_update_check:
            utils.check_if_latest_version()

        cluster_config = _parse_config_file(config_file=args.config_file)
        result = PclusterApi().create_cluster(
            cluster_config=cluster_config,
            cluster_name=args.cluster_name,
            region=utils.get_region(),
            disable_rollback=args.norollback,
            suppress_validators=args.suppress_validators,
            validation_failure_level=args.validation_failure_level,
        )
        if isinstance(result, ClusterInfo):
            print("Cluster creation started successfully.")

            if not args.nowait:
                verified = utils.verify_stack_status(
                    result.stack_name, waiting_states=["CREATE_IN_PROGRESS"], successful_state="CREATE_COMPLETE"
                )
                if not verified:
                    LOGGER.critical("\nCluster creation failed.  Failed events:")
                    utils.log_stack_failure_recursive(result.stack_name)
                    sys.exit(1)

                LOGGER.info("")
                result = PclusterApi().describe_cluster(cluster_name=args.cluster_name, region=utils.get_region())
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


def _print_compute_fleet_status(cluster_name, stack_outputs):
    if utils.get_stack_output_value(stack_outputs, "Scheduler") == "slurm":
        status_manager = ComputeFleetStatusManager(cluster_name)
        compute_fleet_status = status_manager.get_status()
        if compute_fleet_status:
            LOGGER.info("ComputeFleetStatus: %s", compute_fleet_status)


def print_stack_outputs(stack_outputs):
    """
    Print a limited set of the CloudFormation Stack outputs.

    :param stack_outputs: the stack outputs dictionary
    """
    whitelisted_outputs = [
        "ClusterUser",
        "MasterPrivateIP",
        "MasterPublicIP",
        "BatchComputeEnvironmentArn",
        "BatchJobQueueArn",
        "BatchJobDefinitionArn",
        "BatchJobDefinitionMnpArn",
        "BatchUserRole",
        "GangliaPrivateURL",
        "GangliaPublicURL",
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
    if not args.color:
        return stack_status
    end = "0m"
    status_to_color = {"COMPLETE": "0;32m", "FAILED": "0;31m", "IN_PROGRESS": "10;33m"}
    for status_label in status_to_color:
        if status_label in stack_status:
            return "\033[%s%s\033[%s" % (status_to_color[status_label], stack_status, end)


def list_clusters(args):
    """List existing clusters."""
    try:
        result = PclusterApi().list_clusters(region=utils.get_region())
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
        result = PclusterApi().describe_cluster(cluster_name=args.cluster_name, region=utils.get_region())
        if isinstance(result, ClusterInfo):
            cluster_instances = []
            if result.head_node:
                cluster_instances.append(("Head node\t", result.head_node.id))

            if result.compute_instances:
                for instance in result.compute_instances:
                    cluster_instances.append(("Compute node\t", instance.id))

            if result.scheduler == "awsbatch":
                LOGGER.info("Run 'awsbhosts --cluster %s' to list the compute instances", args.cluster_name)

            for instance in cluster_instances:
                LOGGER.info("%s         %s", instance[0], instance[1])
        else:
            utils.error(f"Unable to retrieve the instances of the cluster.\n{result.message}")
    except KeyboardInterrupt:
        LOGGER.info("Exiting...")
        sys.exit(0)


def ssh(args, extra_args):
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

        result = PclusterApi().describe_cluster(cluster_name=args.cluster_name, region=utils.get_region())
        if isinstance(result, ClusterInfo):

            # build command
            cmd = "ssh {CFN_USER}@{MASTER_IP} {ARGS}".format(
                CFN_USER=result.user,
                MASTER_IP=result.head_node_ip,
                ARGS=" ".join(cmd_quote(str(arg)) for arg in extra_args),
            )

            # run command
            log_message = "SSH command: {0}".format(cmd)
            if not args.dryrun:
                LOGGER.debug(log_message)
                os.system(cmd)
            else:
                LOGGER.info(log_message)
        else:
            utils.error(f"Unable to connect to the cluster.\n{result.message}")

    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


def status(args):  # noqa: C901 FIXME!!!
    """Get cluster status."""
    try:
        result = PclusterApi().describe_cluster(cluster_name=args.cluster_name, region=utils.get_region())
        if isinstance(result, ClusterInfo):
            sys.stdout.write("\rStatus: %s" % result.stack_status)
            sys.stdout.flush()
            if not args.nowait:
                while result.stack_status not in [
                    "CREATE_COMPLETE",
                    "UPDATE_COMPLETE",
                    "UPDATE_ROLLBACK_COMPLETE",
                    "ROLLBACK_COMPLETE",
                    "CREATE_FAILED",
                    "DELETE_FAILED",
                ]:
                    time.sleep(5)
                    result = PclusterApi().describe_cluster(cluster_name=args.cluster_name, region=utils.get_region())

                    events = utils.get_stack_events(result.stack_name)[0]
                    resource_status = (
                        "Status: %s - %s" % (events.get("LogicalResourceId"), events.get("ResourceStatus"))
                    ).ljust(80)
                    sys.stdout.write("\r%s" % resource_status)
                    sys.stdout.flush()
                sys.stdout.write("\rStatus: %s\n" % result.stack_status)
                sys.stdout.flush()
                if result.stack_status in ["CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"]:
                    if isinstance(result, ClusterInfo) and result.head_node:
                        head_node_state = result.head_node.state
                        LOGGER.info("MasterServer: %s" % head_node_state.upper())
                        if head_node_state == "running":
                            print_stack_outputs(result.stack_outputs)
                    _print_compute_fleet_status(args.cluster_name, result.stack_outputs)
                elif result.stack_status in ["ROLLBACK_COMPLETE", "CREATE_FAILED", "DELETE_FAILED"]:
                    events = utils.get_stack_events(result.stack_name)
                    for event in events:
                        if event.get("ResourceStatus") in ["CREATE_FAILED", "DELETE_FAILED", "UPDATE_FAILED"]:
                            LOGGER.info(
                                "%s %s %s %s %s",
                                event.get("Timestamp"),
                                event.get("ResourceStatus"),
                                event.get("ResourceType"),
                                event.get("LogicalResourceId"),
                                event.get("ResourceStatusReason"),
                            )
            else:
                sys.stdout.write("\n")
                sys.stdout.flush()

        else:
            utils.error(f"Unable to retrieve the status of the cluster.\n{result.message}")

    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


def delete(args):  # noqa: C901
    """Delete cluster described by cluster_name."""
    LOGGER.info("Deleting: %s", args.cluster_name)
    LOGGER.debug("CLI args: %s", str(args))
    try:
        # delete cluster raises an exception if stack does not exist
        result = PclusterApi().delete_cluster(args.cluster_name, utils.get_region(), args.keep_logs)
        if isinstance(result, ClusterInfo):
            print("Cluster deletion started correctly.")
        else:
            utils.error(f"Cluster deletion failed. {result.message}")

        sys.stdout.write("\rStatus: %s" % result.stack_status)
        sys.stdout.flush()
        LOGGER.debug("Status: %s", result.stack_status)
        if not args.nowait:
            while result.stack_status == "DELETE_IN_PROGRESS":
                time.sleep(5)
                result = PclusterApi().describe_cluster(cluster_name=args.cluster_name, region=utils.get_region())
                if isinstance(result, ClusterInfo):
                    events = utils.get_stack_events(result.stack_name, raise_on_error=True)[0]
                    resource_status = (
                        "Status: %s - %s" % (events.get("LogicalResourceId"), events.get("ResourceStatus"))
                    ).ljust(80)
                    sys.stdout.write("\r%s" % resource_status)
                    sys.stdout.flush()
                elif isinstance(result, ApiFailure):
                    # If stack is already deleted
                    if f"Cluster {args.cluster_name} doesn't exist." in result.message:
                        LOGGER.warning(f"\nCluster {args.cluster_name} has already been deleted or does not exist.")
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
            LOGGER.warning(f"\nCluster {args.cluster_name} has already been deleted or does not exist.")
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
            cluster_name=args.cluster_name, region=utils.get_region(), status=ComputeFleetStatus.START_REQUESTED
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
            cluster_name=args.cluster_name, region=utils.get_region(), status=ComputeFleetStatus.STOP_REQUESTED
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
            imagebuilder_config=load_yaml_dict(args.config_file), image_name=args.image_name, region=utils.get_region()
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
        cluster_config = _parse_config_file(config_file=args.config_file)
        # delete cluster raises an exception if stack does not exist
        result = PclusterApi().update_cluster(cluster_config, args.cluster_name, utils.get_region())
        if isinstance(result, ClusterInfo):
            print("Cluster update started correctly.")
        else:
            utils.error(f"Cluster update failed. {result.message}")
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)
