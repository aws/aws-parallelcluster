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
import sys
import time
from builtins import str

import boto3
import pkg_resources
from botocore.exceptions import ClientError
from tabulate import tabulate

import pcluster.utils as utils
from pcluster.config.pcluster_config import PclusterConfig
from pcluster.constants import PCLUSTER_STACK_PREFIX

LOGGER = logging.getLogger(__name__)


def _create_bucket_with_batch_resources(stack_name, region):
    """
    Create a bucket associated to the given stack and upload batch resources.

    Returns the bucket name if both creation and upload succeed.
    """
    batch_resources = pkg_resources.resource_filename(__name__, "resources/batch")
    s3_bucket_name = utils.generate_random_bucket_name(stack_name)
    LOGGER.debug("Creating S3 bucket for AWS Batch resources, named %s", s3_bucket_name)

    try:
        utils.create_s3_bucket(s3_bucket_name, region)
    except ClientError:
        LOGGER.error("Unable to create S3 bucket %s.", s3_bucket_name)
        raise

    try:
        utils.upload_resources_artifacts(s3_bucket_name, root=batch_resources)
    except Exception:
        LOGGER.error("Unable to upload AWS Batch resources to the S3 bucket %s.", s3_bucket_name)
        utils.delete_s3_bucket(s3_bucket_name)
        raise

    return s3_bucket_name


def version():
    return utils.get_installed_version()


def _check_for_updates(pcluster_config):
    """Check for updates."""
    update_check = pcluster_config.get_section("global").get_param_value("update_check")
    if update_check:
        utils.check_if_latest_version()


def create(args):  # noqa: C901 FIXME!!!
    LOGGER.info("Beginning cluster creation for cluster: %s", args.cluster_name)
    LOGGER.debug("Building cluster config based on args %s", str(args))

    # Build the config based on args
    pcluster_config = PclusterConfig(
        config_file=args.config_file, cluster_label=args.cluster_template, fail_on_file_absence=True
    )
    pcluster_config.validate()
    # get CFN parameters, template url and tags from config
    cluster_section = pcluster_config.get_section("cluster")
    cfn_params = pcluster_config.to_cfn()

    _check_for_updates(pcluster_config)

    batch_bucket_name = None
    try:
        cfn_client = boto3.client("cloudformation")
        stack_name = utils.get_stack_name(args.cluster_name)

        # If scheduler is awsbatch create bucket with resources
        if cluster_section.get_param_value("scheduler") == "awsbatch":
            batch_bucket_name = _create_bucket_with_batch_resources(stack_name, pcluster_config.region)
            cfn_params["ResourcesS3Bucket"] = batch_bucket_name

        LOGGER.info("Creating stack named: %s", stack_name)
        LOGGER.debug(cfn_params)

        # determine the CloudFormation Template URL to use
        template_url = _evaluate_pcluster_template_url(pcluster_config, preferred_template_url=args.template_url)

        # merge tags from configuration, command-line and internal ones
        tags = _evaluate_tags(pcluster_config, preferred_tags=args.tags)

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
        if batch_bucket_name:
            utils.delete_s3_bucket(batch_bucket_name)
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)
    except KeyError as e:
        LOGGER.critical("ERROR: KeyError - reason:\n%s", e)
        if batch_bucket_name:
            utils.delete_s3_bucket(batch_bucket_name)
        sys.exit(1)
    except Exception as e:
        LOGGER.critical(e)
        if batch_bucket_name:
            utils.delete_s3_bucket(batch_bucket_name)
        sys.exit(1)


def _evaluate_pcluster_template_url(pcluster_config, preferred_template_url=None):
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
    if configured_tags:
        tags.update(configured_tags)

    if preferred_tags:
        # add tags from command line parameter, by overriding configured ones
        tags.update(preferred_tags)

    # add pcluster version
    tags["Version"] = utils.get_installed_version()

    # convert to CFN tags
    return [{"Key": tag, "Value": tags[tag]} for tag in tags]


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
    except Exception:
        pass
    return is_ganglia_enabled


def start(args):
    """Restore ASG limits or awsbatch CE to min/max/desired."""
    stack_name = utils.get_stack_name(args.cluster_name)
    pcluster_config = PclusterConfig(config_file=args.config_file, cluster_name=args.cluster_name)
    cluster_section = pcluster_config.get_section("cluster")

    if cluster_section.get_param_value("scheduler") == "awsbatch":
        LOGGER.info("Enabling AWS Batch compute environment : %s", args.cluster_name)
        max_vcpus = cluster_section.get_param_value("max_vcpus")
        desired_vcpus = cluster_section.get_param_value("desired_vcpus")
        min_vcpus = cluster_section.get_param_value("min_vcpus")
        ce_name = utils.get_batch_ce(stack_name)
        _start_batch_ce(ce_name=ce_name, min_vcpus=min_vcpus, desired_vcpus=desired_vcpus, max_vcpus=max_vcpus)
    else:
        LOGGER.info("Starting compute fleet : %s", args.cluster_name)
        max_queue_size = cluster_section.get_param_value("max_queue_size")
        min_desired_size = (
            cluster_section.get_param_value("initial_queue_size")
            if cluster_section.get_param_value("maintain_initial_size")
            else 0
        )
        asg_name = utils.get_asg_name(stack_name)
        utils.set_asg_limits(asg_name=asg_name, min=min_desired_size, max=max_queue_size, desired=min_desired_size)


def stop(args):
    """Set ASG limits or awsbatch ce to min/max/desired = 0/0/0."""
    stack_name = utils.get_stack_name(args.cluster_name)
    pcluster_config = PclusterConfig(config_file=args.config_file, cluster_name=args.cluster_name)
    cluster_section = pcluster_config.get_section("cluster")

    if cluster_section.get_param_value("scheduler") == "awsbatch":
        LOGGER.info("Disabling AWS Batch compute environment : %s", args.cluster_name)
        ce_name = utils.get_batch_ce(stack_name)
        _stop_batch_ce(ce_name=ce_name)
    else:
        LOGGER.info("Stopping compute fleet : %s", args.cluster_name)
        asg_name = utils.get_asg_name(stack_name)
        utils.set_asg_limits(asg_name=asg_name, min=0, max=0, desired=0)


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


def _poll_master_server_state(stack_name):
    ec2 = boto3.client("ec2")
    try:
        master_id = utils.get_master_server_id(stack_name)
        instance = ec2.describe_instance_status(InstanceIds=[master_id]).get("InstanceStatuses")[0]
        state = instance.get("InstanceState").get("Name")
        sys.stdout.write("\rMasterServer: %s" % state.upper())
        sys.stdout.flush()
        while state not in ["running", "stopped", "terminated", "shutting-down"]:
            time.sleep(5)
            state = (
                ec2.describe_instance_status(InstanceIds=[master_id])
                .get("InstanceStatuses")[0]
                .get("InstanceState")
                .get("Name")
            )
            master_status = "\r\033[KMasterServer: %s" % state.upper()
            sys.stdout.write(master_status)
            sys.stdout.flush()
        if state in ["terminated", "shutting-down"]:
            LOGGER.info("State: %s is irrecoverable. Cluster needs to be re-created.", state)
            sys.exit(1)
        master_status = "\rMasterServer: %s\n" % state.upper()
        sys.stdout.write(master_status)
        sys.stdout.flush()
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.stdout.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)

    return state


def _get_ec2_instances(stack):
    resources = utils.get_stack_resources(stack)
    temp_instances = [r for r in resources if r.get("ResourceType") == "AWS::EC2::Instance"]

    stack_instances = []
    for instance in temp_instances:
        stack_instances.append([instance.get("LogicalResourceId"), instance.get("PhysicalResourceId")])

    return stack_instances


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


def _stop_batch_ce(ce_name):
    boto3.client("batch").update_compute_environment(computeEnvironment=ce_name, state="DISABLED")


def instances(args):
    stack_name = utils.get_stack_name(args.cluster_name)
    pcluster_config = PclusterConfig(config_file=args.config_file, cluster_name=args.cluster_name)
    cluster_section = pcluster_config.get_section("cluster")

    instances = []
    instances.extend(_get_ec2_instances(stack_name))

    if cluster_section.get_param_value("scheduler") != "awsbatch":
        instances.extend(utils.get_asg_instances(stack_name))

    for instance in instances:
        LOGGER.info("%s         %s", instance[0], instance[1])

    if cluster_section.get_param_value("scheduler") == "awsbatch":
        LOGGER.info("Run 'awsbhosts --cluster %s' to list the compute instances", args.cluster_name)


def ssh(args, extra_args):  # noqa: C901 FIXME!!!
    """
    Execute an SSH command to the master instance, according to the [aliases] section if there.

    :param args: pcluster CLI args
    :param extra_args: pcluster CLI extra_args
    """
    pcluster_config = PclusterConfig(fail_on_error=False)  # FIXME it always search for the default config file
    if args.command in pcluster_config.get_section("aliases").params:
        ssh_command = pcluster_config.get_section("aliases").get_param_value(args.command)
    else:
        ssh_command = "ssh {CFN_USER}@{MASTER_IP} {ARGS}"

    try:
        master_ip, username = utils.get_master_ip_and_username(args.cluster_name)

        try:
            from shlex import quote as cmd_quote
        except ImportError:
            from pipes import quote as cmd_quote

        # build command
        cmd = ssh_command.format(
            CFN_USER=username, MASTER_IP=master_ip, ARGS=" ".join(cmd_quote(str(arg)) for arg in extra_args)
        )

        # run command
        log_message = "SSH command: {0}".format(cmd)
        if not args.dryrun:
            LOGGER.debug(log_message)
            os.system(cmd)
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
            if stack.get("StackStatus") in ["CREATE_COMPLETE", "UPDATE_COMPLETE"]:
                state = _poll_master_server_state(stack_name)
                if state == "running":
                    _print_stack_outputs(stack)
            elif stack.get("StackStatus") in [
                "ROLLBACK_COMPLETE",
                "CREATE_FAILED",
                "DELETE_FAILED",
                "UPDATE_ROLLBACK_COMPLETE",
            ]:
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


def _get_unretained_cw_log_group_resource_keys(template):
    """Return the keys to all CloudWatch log group resources in template if the resource is not to be retained."""
    unretained_cw_log_group_keys = []
    for key, resource in template.get("Resources", {}).items():
        if resource.get("Type") == "AWS::Logs::LogGroup" and resource.get("DeletionPolicy") != "Retain":
            unretained_cw_log_group_keys.append(key)
    return unretained_cw_log_group_keys


def _persist_stack_resources(stack, template, keys):
    """Set the resources in template identified by keys to have a DeletionPolicy of 'Retain'."""
    for key in keys:
        template["Resources"][key]["DeletionPolicy"] = "Retain"
    utils.update_stack_template(stack.get("StackName"), template, stack.get("Parameters"))


def _persist_cloudwatch_log_groups(cluster_name):
    """Enable cluster's CloudWatch log groups to persist past cluster deletion."""
    LOGGER.info("Configuring {0}'s CloudWatch log groups to persist past cluster deletion.".format(cluster_name))
    substacks = utils.get_cluster_substacks(cluster_name)
    substack_template_pairs = [(stack, utils.get_stack_template(stack.get("StackName"))) for stack in substacks]
    substack_template_keys_triplets = [
        (s, t, _get_unretained_cw_log_group_resource_keys(t)) for s, t in substack_template_pairs
    ]
    for stack, template, keys in substack_template_keys_triplets:
        if keys:  # Only persist the CloudWatch group
            _persist_stack_resources(stack, template, keys)


def _delete_cluster(cluster_name, nowait):
    """Delete cluster described by cluster_name."""
    cfn = boto3.client("cloudformation")
    saw_update = False
    try:
        # delete_stack does not raise an exception if stack does not exist
        # Use describe_stacks to explicitly check if the stack exists
        stack_name = utils.get_stack_name(cluster_name)
        cfn.describe_stacks(StackName=stack_name)
        cfn.delete_stack(StackName=stack_name)
        saw_update = True
        stack_status = utils.get_stack(stack_name, cfn).get("StackStatus")
        sys.stdout.write("\rStatus: %s" % stack_status)
        sys.stdout.flush()
        LOGGER.debug("Status: %s", stack_status)
        if not nowait:
            while stack_status == "DELETE_IN_PROGRESS":
                time.sleep(5)
                stack_status = utils.get_stack(stack_name, cfn, raise_on_error=True).get("StackStatus")
                events = utils.get_stack_events(stack_name, raise_on_error=True)[0]
                resource_status = (
                    "Status: %s - %s" % (events.get("LogicalResourceId"), events.get("ResourceStatus"))
                ).ljust(80)
                sys.stdout.write("\r%s" % resource_status)
                sys.stdout.flush()
            sys.stdout.write("\rStatus: %s\n" % stack_status)
            sys.stdout.flush()
            LOGGER.debug("Status: %s", stack_status)
        else:
            sys.stdout.write("\n")
            sys.stdout.flush()
        if stack_status == "DELETE_FAILED":
            LOGGER.info("Cluster did not delete successfully. Run 'pcluster delete %s' again", cluster_name)
    except ClientError as e:
        if e.response.get("Error").get("Message").endswith("does not exist"):
            if saw_update:
                LOGGER.info("\nCluster deleted successfully.")
                sys.exit(0)
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.stdout.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


def delete(args):
    PclusterConfig.init_aws(config_file=args.config_file)
    LOGGER.info("Deleting: %s", args.cluster_name)
    stack_name = utils.get_stack_name(args.cluster_name)
    if not utils.stack_exists(stack_name):
        if args.keep_logs:
            utils.warn(
                "Stack for {0} does not exist. Cannot prevent its log groups from being deleted.".format(
                    args.cluster_name
                )
            )
        utils.warn("Cluster {0} has already been deleted.".format(args.cluster_name))
        sys.exit(0)
    elif args.keep_logs:
        _persist_cloudwatch_log_groups(args.cluster_name)
    _delete_cluster(args.cluster_name, args.nowait)


def _get_default_template_url(region):
    return (
        "https://{REGION}-aws-parallelcluster.s3.{REGION}.amazonaws.com{SUFFIX}/templates/"
        "aws-parallelcluster-{VERSION}.cfn.json".format(
            REGION=region, SUFFIX=".cn" if region.startswith("cn") else "", VERSION=utils.get_installed_version()
        )
    )
