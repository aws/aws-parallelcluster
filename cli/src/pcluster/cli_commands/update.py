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
from builtins import input

import boto3
from botocore.exceptions import ClientError
from tabulate import tabulate

import pcluster.utils as utils
from pcluster.cluster_model import ClusterModel
from pcluster.commands import evaluate_pcluster_template_url, upload_dashboard_resource, upload_hit_resources
from pcluster.config.config_patch import ConfigPatch
from pcluster.config.pcluster_config import PclusterConfig
from pcluster.config.update_policy import UpdatePolicy

LOGGER = logging.getLogger(__name__)


def execute(args):
    LOGGER.info("Retrieving configuration from CloudFormation for cluster {0}...".format(args.cluster_name))
    base_config = PclusterConfig(config_file=args.config_file, cluster_name=args.cluster_name)
    stack_status = base_config.cfn_stack.get("StackStatus")
    if "IN_PROGRESS" in stack_status:
        utils.error("Cannot execute update while stack is in {} status.".format(stack_status))

    LOGGER.info("Validating configuration file {0}...".format(args.config_file if args.config_file else ""))
    stack_name = utils.get_stack_name(args.cluster_name)
    target_config = PclusterConfig(
        config_file=args.config_file, cluster_label=args.cluster_template, fail_on_file_absence=True
    )
    target_config.validate()

    if _check_cluster_models(base_config, target_config, args.cluster_template) and _check_changes(
        args, base_config, target_config
    ):
        # Update base config settings
        base_config.update(target_config)

        cfn_params = base_config.to_cfn()
        cfn_client = boto3.client("cloudformation")
        _restore_cfn_only_params(cfn_client, args, cfn_params, stack_name, target_config)

        s3_bucket_name = cfn_params["ResourcesS3Bucket"]
        tags = _get_target_config_tags_list(target_config)
        artifact_directory = cfn_params["ArtifactS3RootDirectory"]

        is_hit = utils.is_hit_enabled_cluster(base_config.cfn_stack)
        template_url = None
        if is_hit:
            try:
                upload_hit_resources(
                    s3_bucket_name, artifact_directory, target_config, target_config.to_storage().json_params, tags
                )
            except Exception:
                utils.error("Failed when uploading resources to cluster S3 bucket {0}".format(s3_bucket_name))
            template_url = evaluate_pcluster_template_url(target_config)

        try:
            upload_dashboard_resource(
                s3_bucket_name,
                artifact_directory,
                target_config,
                target_config.to_storage().json_params,
                target_config.to_storage().cfn_params,
            )
        except Exception:
            utils.error("Failed when uploading the dashboard resource to cluster S3 bucket {0}".format(s3_bucket_name))

        _update_cluster(
            args,
            cfn_client,
            cfn_params,
            stack_name,
            use_previous_template=not is_hit,
            template_url=template_url,
            tags=tags,
        )
    else:
        LOGGER.info("Update aborted.")
        sys.exit(1)


def _update_cluster(
    args,
    cfn,
    cfn_params,
    stack_name,
    use_previous_template,
    template_url,
    tags,
):
    LOGGER.info("Updating: %s", args.cluster_name)
    LOGGER.debug("Updating based on args %s", str(args))
    try:
        LOGGER.debug(cfn_params)
        if args.extra_parameters:
            LOGGER.debug("Adding extra parameters to the CFN parameters")
            cfn_params.update(dict(args.extra_parameters))

        cfn_params = [{"ParameterKey": key, "ParameterValue": value} for key, value in cfn_params.items()]
        LOGGER.info("Calling update_stack")
        update_stack_args = {
            "StackName": stack_name,
            "UsePreviousTemplate": use_previous_template,
            "Parameters": cfn_params,
            "Capabilities": ["CAPABILITY_IAM"],
            "Tags": tags,
        }
        if template_url:
            update_stack_args["TemplateURL"] = template_url
        cfn.update_stack(**update_stack_args)
        stack_status = utils.get_stack(stack_name, cfn).get("StackStatus")
        if not args.nowait:
            while stack_status in ["UPDATE_IN_PROGRESS", "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS"]:
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


def _check_changes(args, base_config, target_config):
    can_proceed = True
    if args.force:
        LOGGER.warning(
            "WARNING: Forced update applied. All safety checks will be skipped. Not all updates may be applied and "
            "your cluster may become unstable."
        )

    try:
        patch = ConfigPatch(base_config, target_config)
        patch_allowed, rows = patch.check()
        _print_check_report(patch_allowed, rows, args.force)
        can_proceed = patch_allowed or args.force
    except Exception as e:
        LOGGER.error(e)
        can_proceed = False

    # Final consent from user
    if can_proceed:
        can_proceed = args.yes or input("Do you want to proceed with the update? - Y/N: ").strip().lower() == "y"
    return can_proceed


def _print_check_report(patch_allowed, check_rows, forced):
    # Format of check_rows is:
    # "section", "parameter", "old value", "new value", "check", "reason", "action_needed"
    current_section_name = None
    check_rows.pop(0)  # Remove labels row
    report_rows = [["#", "parameter", "old value", "new value"]]
    report_row_details = []
    report_row_num = 0
    for check_row in check_rows:
        section_name = check_row[0]
        if section_name != current_section_name:
            if current_section_name:
                report_rows.append([])  # Empty line before new sections
            current_section_name = section_name
            report_rows.append(["", "[{0}]".format(utils.ellipsize(section_name, 90)), "", ""])

        report_row_num += 1
        report_row_num_str = "{0:02d}".format(report_row_num)
        failed = not forced and (check_row[4] != UpdatePolicy.CheckResult.SUCCEEDED.value)

        report_rows.append(
            [
                "{0}{1}".format(report_row_num_str, "*" if failed else ""),
                _format_report_column(check_row[1]),
                _format_report_column(check_row[2]),
                _format_report_column(check_row[3]),
            ]
        )

        if failed:
            report_row_details.append(
                "#{0}\n{1}\nHow to fix:\n{2}\n".format(report_row_num_str, check_row[5], check_row[6])
            )

    # Print changes table
    if len(report_rows) > 1:
        print("Found Configuration Changes:\n")
        print(tabulate(report_rows, headers="firstrow"))
        if not forced:
            # Print change details (only if not forced)
            _print_check_details(patch_allowed, report_row_details)
    else:
        print("No changes found in your cluster configuration.")


def _print_check_details(patch_allowed, report_row_details):
    print()
    print("Validating configuration update...")
    if not patch_allowed:
        print(
            "The requested update cannot be performed. Line numbers with an asterisk indicate updates requiring "
            "additional actions. Please review the details below:\n"
        )
        for row_detail in report_row_details:
            print(row_detail)

        print(
            "In case you want to override these checks and proceed with the update please use the --force flag. "
            "Note that the cluster could end up in an unrecoverable state."
        )
    else:
        print("Congratulations! The new configuration can be safely applied to your cluster.")


def _format_report_column(value):
    """Format the provided change value to fit the report table."""
    return utils.ellipsize(value, 30) if value is not None else "-"


def _restore_cfn_only_params(cfn_boto3_client, args, cfn_params, stack_name, target_config):
    cluster_section = target_config.get_section("cluster")

    scheduler = cluster_section.get_param_value("scheduler")
    # Autofill DesiredSize cfn param
    if not args.reset_desired and not utils.is_hit_enabled_scheduler(scheduler):
        _restore_desired_size(cfn_params, stack_name, scheduler)
    elif scheduler == "awsbatch":
        LOGGER.info("reset_desired flag does not work with awsbatch scheduler")

    # Autofill S3 bucket related cfn param
    params = utils.get_stack(stack_name, cfn_boto3_client).get("Parameters")
    # Update of cluster_resource_bucket/ResourcesS3Bucket is not supported
    # We will always restore the value of this parameter from CFN stack
    cfn_params["ResourcesS3Bucket"] = utils.get_cfn_param(params, "ResourcesS3Bucket")
    cfn_params["ArtifactS3RootDirectory"] = utils.get_cfn_param(params, "ArtifactS3RootDirectory")
    cfn_params["RemoveBucketOnDeletion"] = utils.get_cfn_param(params, "RemoveBucketOnDeletion")


def _restore_desired_size(cfn_params, stack_name, scheduler):
    """
    Make the ASG desired capacity to be restored to its current value after the update operation.

    This is done by providing the current value to CloudFormation with the DesiredSize parameter so that the ASG will be
    updated with that capacity instead of the minimum/initial size of the cluster.
    """
    if scheduler != "awsbatch":
        asg_settings = utils.get_asg_settings(stack_name)
        desired_capacity = asg_settings.get("DesiredCapacity")
    else:
        desired_capacity = utils.get_batch_ce_capacity(stack_name)

    # If there are compute nodes running, preserve current desired capacity (if possible)
    if int(cfn_params["MinSize"]) <= desired_capacity <= int(cfn_params["MaxSize"]):
        cfn_params["DesiredSize"] = str(desired_capacity)


def _check_cluster_models(base_config, target_config, cluster_template):
    """
    Check if the cluster models of the two configurations are compatible with the update operation.

    If target configuration is SIT and base is HIT a conversion is required.
    """
    same_cluster_model = target_config.cluster_model == base_config.cluster_model
    if not same_cluster_model:
        conversion_supported = (
            True
            if (target_config.cluster_model == ClusterModel.SIT and base_config.cluster_model == ClusterModel.HIT)
            else False
        )
        if conversion_supported:
            LOGGER.error(
                (
                    "The configuration of the cluster section in the '{config_file}' must be converted to the latest "
                    "format with support for multiple queues before proceeding with the update.\n"
                    "Please run the following command:\n"
                    "pcluster-config convert -c {config_file} {cluster_template_arg} -o <output_file> \n"
                    "Then retry with your converted configuration file by running the following command:\n"
                    "pcluster update -c <output_file> {cluster_template_arg} {cluster_name}"
                ).format(
                    config_file=target_config.config_file,
                    cluster_name=base_config.cluster_name,
                    cluster_template_arg=" -t " + cluster_template if cluster_template else "",
                )
            )
        else:
            LOGGER.error(
                (
                    "The configuration of the cluster section in the '{config_file}' configuration "
                    "file is not compatible with the existing cluster '{cluster_name}'.\n"
                    "Please make sure that you are passing the correct configuration file."
                ).format(
                    config_file=target_config.config_file,
                    cluster_name=base_config.cluster_name,
                )
            )

    return same_cluster_model


def _get_target_config_tags_list(target_config):
    """Construct the target config's tag list."""
    # At cluster creation time we add a version tag.
    # Make sure that's included as well to avoid an unintended change.
    tags_dict = {"Version": utils.get_installed_version()}
    target_config_tags_dict = target_config.get_section("cluster").get_param_value("tags")
    if target_config_tags_dict:
        tags_dict.update(target_config_tags_dict)
    return [{"Key": tag_name, "Value": tag_value} for tag_name, tag_value in tags_dict.items()]
