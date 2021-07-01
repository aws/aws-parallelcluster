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
from typing import List

from tabulate import tabulate

from pcluster import utils
from pcluster.api.pcluster_api import ClusterInfo, PclusterApi
from pcluster.aws.common import get_region
from pcluster.cli_commands.commands import print_stack_outputs, read_config_file
from pcluster.config.update_policy import UpdatePolicy

LOGGER = logging.getLogger(__name__)


def execute(args):
    """Execute update command."""
    LOGGER.info("Updating: %s", args.cluster_name)
    LOGGER.debug("CLI args: %s", str(args))
    try:
        if args.force:
            LOGGER.warning(
                "WARNING: Forced update applied. All safety checks will be skipped. Not all updates may be applied and "
                "your cluster may become unstable."
            )

        cluster_config = read_config_file(config_file=args.config_file)
        result = PclusterApi().update_cluster(
            cluster_config,
            args.cluster_name,
            get_region(),
            suppress_validators=args.suppress_validators,
            force=args.force,
        )
        if isinstance(result, ClusterInfo):
            print("Cluster update started correctly.")

            if not args.nowait:
                verified = utils.verify_stack_status(
                    result.stack_name,
                    waiting_states=["UPDATE_IN_PROGRESS", "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS"],
                    successful_states=["UPDATE_COMPLETE"],
                )
                if not verified:
                    LOGGER.critical("\nCluster update failed.  Failed events:")
                    utils.log_stack_failure_recursive(result.stack_name, failed_states=["UPDATE_FAILED"])
                    sys.exit(1)

                result = PclusterApi().describe_cluster(cluster_name=args.cluster_name, region=get_region())
                if isinstance(result, ClusterInfo):
                    print_stack_outputs(result.stack_outputs)
                else:
                    utils.error(f"Unable to retrieve the status of the cluster.\n{result.message}")
            else:
                LOGGER.info("Status: %s", result.stack_status)
        else:
            print("Cluster update failed. {0}.".format(result.message if result.message else ""))
            if result.validation_failures:
                print(
                    "\nValidation failures:\n{0}".format(
                        "\n".join([f"{result.level.name}: {result.message}" for result in result.validation_failures])
                    )
                )

            if result.update_changes:
                _print_update_changes(changes=result.update_changes, forced=args.force)

    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


def _print_update_changes(changes: List, forced: bool = False):
    """
    Print update failures.

    :param changes: change format is:  section, parameter, old value, new value, check, reason, action_needed
    :param forced: if set to true no details will be shown
    """
    current_section_name = None
    changes.pop(0)  # Remove labels row
    report_rows = [["#", "parameter", "old value", "new value"]]
    report_row_details = []
    report_row_num = 0

    for change in changes:
        section_name = "|{0}|".format(">".join(change[0]) if change[0] else "ROOT")
        if section_name != current_section_name:
            if current_section_name:
                report_rows.append([])  # Empty line before new sections
            current_section_name = section_name
            report_rows.append(["", "{0}".format(utils.ellipsize(section_name, 90)), "", ""])

        report_row_num += 1
        report_row_num_str = "{0:02d}".format(report_row_num)
        failed = not forced and (change[4] != UpdatePolicy.CheckResult.SUCCEEDED.value)

        report_rows.append(
            [
                "{0}{1}".format(report_row_num_str, "*" if failed else ""),
                _format_report_column(change[1]),
                _format_report_column(change[2]),
                _format_report_column(change[3]),
            ]
        )
        if failed:
            report_row_details.append("#{0}\n{1}\nHow to fix:\n{2}\n".format(report_row_num_str, change[5], change[6]))

    # Print changes table
    if len(report_rows) > 1:
        print("Found configuration changes:\n")
        print(tabulate(report_rows, headers="firstrow"))
        if not forced:
            # Print change details (only if not forced)
            print(
                "\nThe requested update cannot be performed. Line numbers with an asterisk indicate updates requiring "
                "additional actions. Please review the details below:\n"
            )
            for row_detail in report_row_details:
                print(row_detail)

            print(
                "In case you want to override these checks and proceed with the update please use the --force flag. "
                "Note that the cluster could end up in an unrecoverable state."
            )
    else:
        print("No changes found in your cluster configuration.")


def _format_report_column(value):
    """Format the provided change value to fit the report table."""
    return utils.ellipsize(value, 30) if value is not None else "-"
