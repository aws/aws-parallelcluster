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
from pcluster.cli_commands.compute_fleet_status_manager import ComputeFleetStatusManager
from pcluster.config.hit_converter import HitConverter
from pcluster.config.pcluster_config import PclusterConfig
from pcluster.constants import PCLUSTER_NAME_MAX_LENGTH, PCLUSTER_NAME_REGEX, PCLUSTER_STACK_PREFIX

LOGGER = logging.getLogger(__name__)


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
            utils.create_s3_bucket(s3_bucket_name, pcluster_config.region)
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


def _check_for_updates(pcluster_config):
    """Check for updates."""
    update_check = pcluster_config.get_section("global").get_param_value("update_check")
    if update_check:
        utils.check_if_latest_version()


def _validate_cluster_name(cluster_name):
    if not re.match(PCLUSTER_NAME_REGEX % (PCLUSTER_NAME_MAX_LENGTH - 1), cluster_name):
        LOGGER.error(
            (
                "Error: The cluster name can contain only alphanumeric characters (case-sensitive) and hyphens. "
                "It must start with an alphabetic character and can't be longer than {} characters."
            ).format(PCLUSTER_NAME_MAX_LENGTH)
        )
        sys.exit(1)


def create(args):  # noqa: C901 FIXME!!!
    LOGGER.info("Beginning cluster creation for cluster: %s", args.cluster_name)
    LOGGER.debug("Building cluster config based on args %s", str(args))

    _validate_cluster_name(args.cluster_name)

    # Build the config based on args
    pcluster_config = PclusterConfig(
        config_file=args.config_file, cluster_label=args.cluster_template, fail_on_file_absence=True
    )
    pcluster_config.validate()

    # Automatic SIT -> HIT conversion, if needed
    HitConverter(pcluster_config).convert()

    # get CFN parameters, template url and tags from config
    storage_data = pcluster_config.to_storage()
    cfn_params = storage_data.cfn_params

    _check_for_updates(pcluster_config)

    bucket_name = None
    artifact_directory = None
    cleanup_bucket = False
    try:
        cfn_client = boto3.client("cloudformation")
        stack_name = utils.get_stack_name(args.cluster_name)

        # merge tags from configuration, command-line and internal ones
        tags = _evaluate_tags(pcluster_config, preferred_tags=args.tags)

        bucket_name, artifact_directory, cleanup_bucket = _setup_bucket_with_resources(
            pcluster_config, storage_data, stack_name, tags
        )
        cfn_params["ResourcesS3Bucket"] = bucket_name
        cfn_params["ArtifactS3RootDirectory"] = artifact_directory
        cfn_params["RemoveBucketOnDeletion"] = str(cleanup_bucket)

        LOGGER.info("Creating stack named: %s", stack_name)

        # determine the CloudFormation Template URL to use
        template_url = evaluate_pcluster_template_url(pcluster_config, preferred_template_url=args.template_url)

        # append extra parameters from command-line
        if args.extra_parameters:
            LOGGER.debug("Adding extra parameters to the CFN parameters")
            cfn_params.update(dict(args.extra_parameters))

        # prepare input parameters for stack creation and create the stack
        LOGGER.debug(cfn_params)
        params = [{"ParameterKey": key, "ParameterValue": value} for key, value in cfn_params.items()]
        stack = cfn_client.create_stack(
            StackName=stack_name,
            TemplateURL=template_url,
            Parameters=params,
            Capabilities=["CAPABILITY_IAM"],
            DisableRollback=args.norollback,
            Tags=tags,
        )
        LOGGER.debug("StackId: %s", stack.get("StackId"))

        if not args.nowait:
            verified = utils.verify_stack_creation(stack_name, cfn_client)
            LOGGER.info("")
            result_stack = utils.get_stack(stack_name, cfn_client)
            _print_stack_outputs(result_stack)
            if not verified:
                sys.exit(1)
        else:
            stack_status = utils.get_stack(stack_name, cfn_client).get("StackStatus")
            LOGGER.info("Status: %s", stack_status)
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.stdout.flush()
        utils.cleanup_s3_resources(bucket_name, artifact_directory, cleanup_bucket)
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        if not utils.stack_exists(stack_name):
            # Cleanup S3 artifacts if stack is not created yet
            utils.cleanup_s3_resources(bucket_name, artifact_directory, cleanup_bucket)
        sys.exit(0)
    except KeyError as e:
        LOGGER.critical("ERROR: KeyError - reason:\n%s", e)
        utils.cleanup_s3_resources(bucket_name, artifact_directory, cleanup_bucket)
        sys.exit(1)
    except Exception as e:
        LOGGER.critical(e)
        utils.cleanup_s3_resources(bucket_name, artifact_directory, cleanup_bucket)
        sys.exit(1)


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


def _evaluate_tags(pcluster_config, preferred_tags=None):
    """
    Merge given tags to the ones defined in the configuration file and convert them into the Key/Value format.

    :param pcluster_config: PclusterConfig, it can contain tags
    :param preferred_tags: tags that must take the precedence before the configured ones
    :return: a merge of the tags + version tag
    """
    tags = {}

    configured_tags = pcluster_config.get_section("cluster").get_param_value("tags")
    _add_intel_tags(pcluster_config, tags)
    if configured_tags:
        tags.update(configured_tags)

    if preferred_tags:
        # add tags from command line parameter, by overriding configured ones
        tags.update(preferred_tags)

    # add pcluster version
    tags["Version"] = utils.get_installed_version()

    # convert to CFN tags
    return [{"Key": tag, "Value": tags[tag]} for tag in tags]


def _add_intel_tags(pcluster_config, tags):
    if pcluster_config.get_section("cluster").get_param_value("enable_intel_hpc_platform"):
        tags.update({"aws-parallelcluster-intel-hpc": "enable_intel_hpc_platform=true"})


def _print_compute_fleet_status(cluster_name, stack):
    outputs = stack.get("Outputs", [])
    if utils.get_stack_output_value(outputs, "IsHITCluster") == "true":
        status_manager = ComputeFleetStatusManager(cluster_name)
        compute_fleet_status = status_manager.get_status()
        if compute_fleet_status:
            LOGGER.info("ComputeFleetStatus: %s", compute_fleet_status)


def _print_stack_outputs(stack):
    """
    Print a limited set of the CloudFormation Stack outputs.

    :param stack: the stack dictionary
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
    ]
    if _is_ganglia_enabled(stack.get("Parameters")):
        whitelisted_outputs.extend(["GangliaPrivateURL", "GangliaPublicURL"])

    for output in stack.get("Outputs", []):
        output_key = output.get("OutputKey")
        if output_key in whitelisted_outputs:
            LOGGER.info("%s: %s", output_key, output.get("OutputValue"))


def _is_ganglia_enabled(parameters):
    is_ganglia_enabled = False
    try:
        cfn_extra_json = utils.get_cfn_param(parameters, "ExtraJson")
        is_ganglia_enabled = json.loads(cfn_extra_json).get("cfncluster").get("ganglia_enabled") == "yes"
    except Exception:  # nosec
        pass
    return is_ganglia_enabled


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


def list_stacks(args):
    # Parse configuration file to read the AWS section
    PclusterConfig.init_aws(config_file=args.config_file)

    try:
        result = []
        for stack in utils.paginate_boto3(boto3.client("cloudformation").describe_stacks):
            if stack.get("ParentId") is None and stack.get("StackName").startswith(PCLUSTER_STACK_PREFIX):
                pcluster_version = _get_pcluster_version_from_stack(stack)
                result.append(
                    [
                        stack.get("StackName")[len(PCLUSTER_STACK_PREFIX) :],  # noqa: E203
                        _colorize(stack.get("StackStatus"), args),
                        pcluster_version,
                    ]
                )
        LOGGER.info(tabulate(result, tablefmt="plain"))
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("Exiting...")
        sys.exit(0)


def _poll_head_node_state(stack_name):
    ec2 = boto3.client("ec2")
    try:
        instances = utils.describe_cluster_instances(stack_name, node_type=utils.NodeType.head_node)
        if not instances:
            LOGGER.error("Cannot retrieve head node status. Exiting...")
            sys.exit(1)
        head_node_id = instances[0].get("InstanceId")
        state = instances[0].get("State").get("Name")
        sys.stdout.write("\rMasterServer: %s" % state.upper())
        sys.stdout.flush()
        while state not in ["running", "stopped", "terminated", "shutting-down"]:
            time.sleep(5)
            state = (
                ec2.describe_instance_status(InstanceIds=[head_node_id])
                .get("InstanceStatuses")[0]
                .get("InstanceState")
                .get("Name")
            )
            head_node_status = "\r\033[KMasterServer: %s" % state.upper()
            sys.stdout.write(head_node_status)
            sys.stdout.flush()
        if state in ["terminated", "shutting-down"]:
            LOGGER.info("State: %s is irrecoverable. Cluster needs to be re-created.", state)
            sys.exit(1)
        head_node_status = "\rMasterServer: %s\n" % state.upper()
        sys.stdout.write(head_node_status)
        sys.stdout.flush()
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.stdout.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)

    return state


def _get_compute_instances(stack):
    instances = utils.describe_cluster_instances(stack, node_type=utils.NodeType.compute)
    return map(lambda i: ("ComputeFleet", i.get("InstanceId")), instances)


def instances(args):
    stack_name = utils.get_stack_name(args.cluster_name)
    PclusterConfig.init_aws(config_file=args.config_file)
    cfn_stack = utils.get_stack(stack_name)
    scheduler = utils.get_cfn_param(cfn_stack.get("Parameters"), "Scheduler")

    instances = []
    head_node_server = utils.describe_cluster_instances(stack_name, node_type=utils.NodeType.head_node)
    if head_node_server:
        instances.append(("MasterServer", head_node_server[0].get("InstanceId")))

    if scheduler != "awsbatch":
        instances.extend(_get_compute_instances(stack_name))

    for instance in instances:
        LOGGER.info("%s         %s", instance[0], instance[1])

    if scheduler == "awsbatch":
        LOGGER.info("Run 'awsbhosts --cluster %s' to list the compute instances", args.cluster_name)


def ssh(args, extra_args):  # noqa: C901 FIXME!!!
    """
    Execute an SSH command to the head node instance, according to the [aliases] section if there.

    :param args: pcluster CLI args
    :param extra_args: pcluster CLI extra_args
    """
    # FIXME it always search for the default config file
    pcluster_config = PclusterConfig(fail_on_error=False, auto_refresh=False)
    if args.command in pcluster_config.get_section("aliases").params:
        ssh_command = pcluster_config.get_section("aliases").get_param_value(args.command)
    else:
        ssh_command = "ssh {CFN_USER}@{MASTER_IP} {ARGS}"

    try:
        head_node_ip, username = utils.get_head_node_ip_and_username(args.cluster_name)
        try:
            from shlex import quote as cmd_quote
        except ImportError:
            from pipes import quote as cmd_quote

        # build command
        cmd = ssh_command.format(
            CFN_USER=username, MASTER_IP=head_node_ip, ARGS=" ".join(cmd_quote(str(arg)) for arg in extra_args)
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
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


def status(args):  # noqa: C901 FIXME!!!
    stack_name = utils.get_stack_name(args.cluster_name)

    # Parse configuration file to read the AWS section
    PclusterConfig.init_aws(config_file=args.config_file)

    cfn = boto3.client("cloudformation")
    try:
        stack = utils.get_stack(stack_name, cfn)
        sys.stdout.write("\rStatus: %s" % stack.get("StackStatus"))
        sys.stdout.flush()
        if not args.nowait:
            while stack.get("StackStatus") not in [
                "CREATE_COMPLETE",
                "UPDATE_COMPLETE",
                "UPDATE_ROLLBACK_COMPLETE",
                "ROLLBACK_COMPLETE",
                "CREATE_FAILED",
                "DELETE_FAILED",
            ]:
                time.sleep(5)
                stack = utils.get_stack(stack_name, cfn)
                events = utils.get_stack_events(stack_name)[0]
                resource_status = (
                    "Status: %s - %s" % (events.get("LogicalResourceId"), events.get("ResourceStatus"))
                ).ljust(80)
                sys.stdout.write("\r%s" % resource_status)
                sys.stdout.flush()
            sys.stdout.write("\rStatus: %s\n" % stack.get("StackStatus"))
            sys.stdout.flush()
            if stack.get("StackStatus") in ["CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"]:
                state = _poll_head_node_state(stack_name)
                if state == "running":
                    _print_stack_outputs(stack)
                _print_compute_fleet_status(args.cluster_name, stack)
            elif stack.get("StackStatus") in ["ROLLBACK_COMPLETE", "CREATE_FAILED", "DELETE_FAILED"]:
                events = utils.get_stack_events(stack_name)
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
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.stdout.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


def _get_default_template_url(region):
    return (
        "https://{REGION}-aws-parallelcluster.s3.{REGION}.amazonaws.com{SUFFIX}/templates/"
        "aws-parallelcluster-{VERSION}.cfn.json".format(
            REGION=region, SUFFIX=".cn" if region.startswith("cn") else "", VERSION=utils.get_installed_version()
        )
    )
