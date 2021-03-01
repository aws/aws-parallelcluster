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

from __future__ import absolute_import, print_function

import json
import logging
import os
import re
import sys
import time
from builtins import str

import boto3
import pkg_resources
from botocore.exceptions import ClientError
from tabulate import tabulate

import pcluster.utils as utils
from api.pcluster_api import ApiFailure, FullClusterInfo, PclusterApi
from common.utils import load_yaml_dict
from pcluster.cli_commands.compute_fleet_status_manager import ComputeFleetStatus, ComputeFleetStatusManager
from pcluster.constants import PCLUSTER_NAME_MAX_LENGTH, PCLUSTER_NAME_REGEX

LOGGER = logging.getLogger(__name__)


# TODO moved
def _setup_bucket_with_resources(pcluster_config, storage_data, stack_name, tags):
    """
    Create pcluster bucket if needed and upload cluster specific resources.

    If no bucket specified, create a bucket associated to the given stack.
    Created bucket needs to be removed on cluster deletion.
    Artifacts are uploaded to {bucket_name}/{artifact_directory}/.
    {artifact_directory}/ will be always be cleaned up on cluster deletion or in case of failure.
    """
    s3_bucket_name = pcluster_config.get_section("cluster").get_param_value("cluster_resource_bucket")
    remove_bucket_on_deletion = False
    # Use "{stack_name}-{random_string}" as directory in bucket
    artifact_directory = utils.generate_random_name_with_prefix(stack_name)
    if not s3_bucket_name or s3_bucket_name == "NONE":
        # Create 1 bucket per cluster named "parallelcluster-{random_string}" if bucket is not provided
        # This bucket needs to be removed on cluster deletion
        s3_bucket_name = utils.generate_random_name_with_prefix("parallelcluster")
        LOGGER.debug("Creating S3 bucket for cluster resources, named %s", s3_bucket_name)
        try:
            utils.create_s3_bucket(s3_bucket_name)
        except Exception:
            LOGGER.error("Unable to create S3 bucket %s.", s3_bucket_name)
            raise
        remove_bucket_on_deletion = True
    else:
        # Use user-provided bucket
        # Do not remove this bucket on deletion, but cleanup artifact directory
        try:
            utils.check_s3_bucket_exists(s3_bucket_name)
        except Exception as e:
            LOGGER.error("Unable to access config-specified S3 bucket %s: %s", s3_bucket_name, e)
            raise

    _upload_cluster_artifacts(
        s3_bucket_name, artifact_directory, pcluster_config, storage_data, tags, remove_bucket_on_deletion
    )

    return s3_bucket_name, artifact_directory, remove_bucket_on_deletion


# TODO moved
def _upload_cluster_artifacts(
    s3_bucket_name, artifact_directory, pcluster_config, storage_data, tags, remove_bucket_on_deletion
):
    try:
        scheduler = pcluster_config.get_section("cluster").get_param_value("scheduler")
        resources_dirs = ["resources/custom_resources"]
        if scheduler == "awsbatch":
            resources_dirs.append("resources/batch")

        for resources_dir in resources_dirs:
            resources = pkg_resources.resource_filename(__name__, resources_dir)
            utils.upload_resources_artifacts(
                s3_bucket_name,
                artifact_directory,
                root=resources,
            )
        if utils.is_hit_enabled_scheduler(scheduler):
            upload_hit_resources(s3_bucket_name, artifact_directory, pcluster_config, storage_data.json_params, tags)

        upload_dashboard_resource(
            s3_bucket_name, artifact_directory, pcluster_config, storage_data.json_params, storage_data.cfn_params
        )
    except Exception as e:
        LOGGER.error("Unable to upload cluster resources to the S3 bucket %s due to exception: %s", s3_bucket_name, e)
        utils.cleanup_s3_resources(s3_bucket_name, artifact_directory, remove_bucket_on_deletion)
        raise


# TODO to be deleted
def upload_hit_resources(bucket_name, artifact_directory, pcluster_config, json_params, tags=None):
    if tags is None:
        tags = []
    hit_template_url = pcluster_config.get_section("cluster").get_param_value(
        "hit_template_url"
    ) or "{bucket_url}/templates/compute-fleet-hit-substack-{version}.cfn.yaml".format(
        bucket_url=utils.get_bucket_url(pcluster_config.region), version=utils.get_installed_version()
    )
    s3_client = boto3.client("s3")

    try:
        result = s3_client.put_object(
            Bucket=bucket_name,
            Body=json.dumps(json_params),
            Key="{artifact_directory}/configs/cluster-config.json".format(artifact_directory=artifact_directory),
        )
        file_contents = utils.read_remote_file(hit_template_url)
        rendered_template = utils.render_template(file_contents, json_params, tags, result.get("VersionId"))
    except ClientError as client_error:
        LOGGER.error("Error when uploading cluster configuration file to bucket %s: %s", bucket_name, client_error)
        raise
    except Exception as e:
        LOGGER.error("Error when generating CloudFormation template from url %s: %s", hit_template_url, e)
        raise

    try:
        s3_client.put_object(
            Bucket=bucket_name,
            Body=rendered_template,
            Key="{artifact_directory}/templates/compute-fleet-hit-substack.rendered.cfn.yaml".format(
                artifact_directory=artifact_directory
            ),
        )
    except Exception as e:
        LOGGER.error("Error when uploading CloudFormation template to bucket %s: %s", bucket_name, e)
        raise


def upload_dashboard_resource(bucket_name, artifact_directory, pcluster_config, json_params, cfn_params):
    params = {"json_params": json_params, "cfn_params": cfn_params}
    cw_dashboard_template_url = pcluster_config.get_section("cluster").get_param_value(
        "cw_dashboard_template_url"
    ) or "{bucket_url}/templates/cw-dashboard-substack-{version}.cfn.yaml".format(
        bucket_url=utils.get_bucket_url(pcluster_config.region),
        version=utils.get_installed_version(),
    )

    try:
        file_contents = utils.read_remote_file(cw_dashboard_template_url)
        rendered_template = utils.render_template(file_contents, params, {})
    except Exception as e:
        LOGGER.error(
            "Error when generating CloudWatch Dashboard template from path %s: %s", cw_dashboard_template_url, e
        )
        raise

    try:
        boto3.client("s3").put_object(
            Bucket=bucket_name,
            Body=rendered_template,
            Key="{artifact_directory}/templates/cw-dashboard-substack.rendered.cfn.yaml".format(
                artifact_directory=artifact_directory
            ),
        )
    except Exception as e:
        LOGGER.error("Error when uploading CloudWatch Dashboard template to bucket %s: %s", bucket_name, e)


def version():
    return utils.get_installed_version()


def _validate_cluster_name(cluster_name):
    if not re.match(PCLUSTER_NAME_REGEX % (PCLUSTER_NAME_MAX_LENGTH - 1), cluster_name):
        LOGGER.error(
            (
                "Error: The cluster name can contain only alphanumeric characters (case-sensitive) and hyphens. "
                "It must start with an alphabetic character and can't be longer than {} characters."
            ).format(PCLUSTER_NAME_MAX_LENGTH)
        )
        sys.exit(1)


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

    if not args.disable_update_check:
        utils.check_if_latest_version()

    cluster_config = _parse_config_file(config_file=args.config_file)
    result = PclusterApi().create_cluster(
        cluster_config=cluster_config,
        cluster_name=args.cluster_name,
        region=utils.get_region(),
        disable_rollback=args.norollback,
    )
    if isinstance(result, FullClusterInfo):
        print(f"Cluster creation started successfully. {result}")

        if not args.nowait:
            verified = utils.verify_stack_creation(result.stack_name)
            LOGGER.info("")

            result = PclusterApi().describe_cluster(cluster_name=args.cluster_name, region=utils.get_region())
            if isinstance(result, FullClusterInfo):
                # result_stack = utils.get_stack(stack_name, cfn_client)
                _print_stack_outputs(result.stack_outputs)
            else:
                utils.error(f"Unable to retrieve the status of the cluster.\n{result.message}")
            if not verified:
                sys.exit(1)
        else:
            result = PclusterApi().describe_cluster(cluster_name=args.cluster_name, region=utils.get_region())
            if isinstance(result, FullClusterInfo):
                LOGGER.info("Status: %s", result.stack_status)
            else:
                utils.error(f"Unable to retrieve the status of the cluster.\n{result.message}")

    else:
        message = "Cluster creation failed. {0}.".format(result.message if result.message else "")
        if result.validation_failures:
            message += "\nValidation failures:\n"
            message += "\n".join([f"{result.level.name}: {result.message}" for result in result.validation_failures])

        utils.error(message)


def evaluate_pcluster_template_url(pcluster_config, preferred_template_url=None):
    """
    Determine the CloudFormation Template URL to use.

    Order is 1) preferred_template_url 2) Config file 3) default for version + region.

    :param pcluster_config: PclusterConfig, it can contain the template_url
    :param preferred_template_url: preferred template url to use, if not None
    :return: the evaluated template url
    """
    configured_template_url = pcluster_config.get_section("cluster").get_param_value("template_url")

    return preferred_template_url or configured_template_url or _get_default_template_url(pcluster_config.region)


def _print_compute_fleet_status(cluster_name, stack_outputs):
    if utils.get_stack_output_value(stack_outputs, "IsHITCluster") == "true":
        status_manager = ComputeFleetStatusManager(cluster_name)
        compute_fleet_status = status_manager.get_status()
        if compute_fleet_status:
            LOGGER.info("ComputeFleetStatus: %s", compute_fleet_status)


def _print_stack_outputs(stack_outputs):
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


def _get_pcluster_version_from_stack(stack):
    """
    Get the version of the stack if tagged.

    :param stack: stack object
    :return: version or empty string
    """
    return next((tag.get("Value") for tag in stack.get("Tags") if tag.get("Key") == "Version"), "")


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
        if isinstance(result, FullClusterInfo):
            cluster_instances = []
            head_node_instance = result.head_node
            if head_node_instance:
                cluster_instances.append(("Head node\t", head_node_instance.id))

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
        result = PclusterApi().describe_cluster(cluster_name=args.cluster_name, region=utils.get_region())
        if isinstance(result, FullClusterInfo):
            try:
                from shlex import quote as cmd_quote
            except ImportError:
                from pipes import quote as cmd_quote

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
        if isinstance(result, FullClusterInfo):
            # print(f"{result}")
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
                    head_node_state = result.head_node.state
                    LOGGER.info("MasterServer: %s" % head_node_state.upper())

                    if head_node_state == "running":
                        _print_stack_outputs(result.stack_outputs)
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


def _get_default_template_url(region):
    return (
        "https://{REGION}-aws-parallelcluster.s3.{REGION}.amazonaws.com{SUFFIX}/templates/"
        "aws-parallelcluster-{VERSION}.cfn.json".format(
            REGION=region, SUFFIX=".cn" if region.startswith("cn") else "", VERSION=utils.get_installed_version()
        )
    )
