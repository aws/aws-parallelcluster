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
import time

import boto3
from botocore.exceptions import ClientError

from pcluster import utils
from pcluster.config.pcluster_config import PclusterConfig

LOGGER = logging.getLogger(__name__)


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


def _persist_cloudwatch_log_groups(cluster_name):
    """Enable cluster's CloudWatch log groups to persist past cluster deletion."""
    LOGGER.info("Configuring {0}'s CloudWatch log groups to persist past cluster deletion.".format(cluster_name))
    substacks = utils.get_cluster_substacks(cluster_name)
    cw_substack = next((stack for stack in substacks if "CloudWatchLogsSubstack" in stack.get("StackName")), None)
    if cw_substack:
        cw_substack_template = utils.get_stack_template(cw_substack.get("StackName"))
        log_group_keys = _get_unretained_cw_log_group_resource_keys(cw_substack_template)
        if log_group_keys:  # Only persist the CloudWatch group
            _persist_stack_resources(cw_substack, cw_substack_template, log_group_keys)


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
    try:
        utils.update_stack_template(stack.get("StackName"), template, stack.get("Parameters"))
    except ClientError as client_err:
        utils.error(
            "Unable to persist logs on cluster deletion, failed with error: {emsg}.\n"
            "If you want to continue, please retry without the --keep-logs flag.".format(
                emsg=client_err.response.get("Error").get("Message")
            )
        )


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
