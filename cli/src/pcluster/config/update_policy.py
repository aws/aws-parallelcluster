# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from enum import Enum

from pcluster import utils


class UpdatePolicy(object):
    """Describes the policy that rules the update of a configuration parameter."""

    class CheckResult(Enum):
        """Valid results for change checks."""

        SUCCEEDED = "SUCCEEDED"
        ACTION_NEEDED = "ACTION NEEDED"
        FAILED = "FAILED"

    def __init__(
        self,
        base_policy=None,
        level=None,
        fail_reason=None,
        action_needed=None,
        condition_checker=None,
        print_succeeded=True,
    ):
        self.fail_reason = None
        self.action_needed = None
        self.condition_checker = None
        self.print_succeeded = print_succeeded
        self.level = 0

        if base_policy:
            self.fail_reason = base_policy.fail_reason
            self.action_needed = base_policy.action_needed
            self.condition_checker = base_policy.condition_checker
            self.level = base_policy.level

        if level:
            self.level = level
        if fail_reason:
            self.fail_reason = fail_reason
        if action_needed:
            self.action_needed = action_needed
        if condition_checker:
            self.condition_checker = condition_checker

    def check(self, change, patch):
        """
        Check if the update can be safely performed.

        Based on the policy condition checker, the result can be FAILED, SUCCEEDED or ACTION_NEEDED.
        :param change: The change to check
        :param patch: The ConfigPatch the change belongs to
        :return: FAILED, SUCCEEDED or ACTION_NEEDED
        """
        if self.condition_checker:
            if self.condition_checker(change, patch):
                result = UpdatePolicy.CheckResult.SUCCEEDED
                fail_reason = "-"
                action_needed = None
                print_change = self.print_succeeded
            else:
                result = UpdatePolicy.CheckResult.ACTION_NEEDED
                fail_reason = self.fail_reason
                action_needed = self.action_needed
                print_change = True
        else:
            # No condition checker means no chance of getting a successful check result, so CheckResult.FAILED is
            # returned unconditionally
            result = UpdatePolicy.CheckResult.FAILED
            fail_reason = self.fail_reason
            action_needed = self.action_needed
            print_change = True

        if callable(action_needed):
            action_needed = action_needed(change, patch)

        if callable(fail_reason):
            fail_reason = fail_reason(change, patch)

        return result, fail_reason, action_needed, print_change

    def __eq__(self, other):
        if not isinstance(other, UpdatePolicy):
            # don't attempt to compare against unrelated types
            return NotImplemented

        return self.fail_reason == other.fail_reason and self.level == other.level


# Common fail_reason messages
UpdatePolicy.FAIL_REASONS = {
    "ebs_volume_resize": "Updating the file system after a resize operation requires commands specific to your "
    "operating system.",
    "ebs_sections_change": "EBS sections cannot be added or removed during a 'pcluster update' operation",
    "extra_json_update": lambda change, patch: "Updating the extra_json parameter is not supported because it only "
    "applies updates to compute nodes. If you still want to proceed, first stop the cluster with the "
    "following command:\n{0} -c {1} {2} and then run an update with the --force flag".format(
        "pcluster stop", patch.config_file, patch.cluster_name
    ),
}

# Common action_needed messages
UpdatePolicy.ACTIONS_NEEDED = {
    "ebs_volume_update": "Follow the instructions at {0}#{1} to modify your volume from AWS Console.".format(
        "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/requesting-ebs-volume-modifications.html",
        "modify-ebs-volume",
    ),
    "pcluster_stop": lambda change, patch: "Stop the cluster with the following command:\n{0} -c {1} {2}".format(
        "pcluster stop", patch.config_file, patch.cluster_name
    ),
}


def _check_min_count(change, patch):
    is_fleet_stopped = not utils.cluster_has_running_capacity(patch.stack_name)
    if is_fleet_stopped:
        return True

    new_min, old_min = change.new_value, change.old_value
    old_max = patch.base_config.get_section(change.section_key, change.section_label).get_param_value("max_count")
    new_max = patch.target_config.get_section(change.section_key, change.section_label).get_param_value("max_count")
    return new_min >= old_min and new_max - new_min >= old_max - old_min


def _is_bucket_pcluster_generated(stack_name):
    params = utils.get_stack(stack_name).get("Parameters")
    return utils.get_cfn_param(params, "RemoveBucketOnDeletion") == "True"


def _check_generated_bucket(change, patch):

    # If bucket is generated (no cluster_resource_bucket specified when creating) and no change in config
    # Old value is retrieve from CFN's ResourcesS3Bucket param, and new value is from config(not specified)
    # Actual ResourcesS3Bucket will not change when updating, so no actual change when update is applied
    # Since there is no change, user should not be informed of a change/diff
    # Print no diff and proceed with updating other parameters
    # Else display diff
    # Inform user cluster_resource_bucket/ResourcesS3Bucket will not be updated even if force update
    return _is_bucket_pcluster_generated(patch.stack_name) and not change.new_value


# Base policies

# Update is ignored
UpdatePolicy.IGNORED = UpdatePolicy(
    level=-10,
    fail_reason="-",
    condition_checker=(lambda change, patch: True),
    # Ignored changes are not shown
    print_succeeded=False,
)

# Update supported
UpdatePolicy.SUPPORTED = UpdatePolicy(level=0, fail_reason="-", condition_checker=(lambda change, patch: True))

# Checks resize of max_vcpus in Batch Compute Environment
UpdatePolicy.AWSBATCH_CE_MAX_RESIZE = UpdatePolicy(
    level=1,
    fail_reason=lambda change, patch: "Max vCPUs can not be lower than the current Desired vCPUs ({0})".format(
        utils.get_batch_ce_capacity(patch.stack_name)
    ),
    action_needed=UpdatePolicy.ACTIONS_NEEDED["pcluster_stop"],
    condition_checker=lambda change, patch: utils.get_batch_ce_capacity(patch.stack_name)
    <= patch.target_config.get_section("cluster").get_param_value("max_vcpus"),
)

# Checks resize of max_count
UpdatePolicy.MAX_COUNT = UpdatePolicy(
    level=1,
    fail_reason=lambda change, patch: "Shrinking a queue requires the compute fleet to be stopped first",
    action_needed=UpdatePolicy.ACTIONS_NEEDED["pcluster_stop"],
    condition_checker=lambda change, patch: not utils.cluster_has_running_capacity(patch.stack_name)
    or change.new_value >= change.old_value,
)

# Checks resize of min_count
UpdatePolicy.MIN_COUNT = UpdatePolicy(
    level=1,
    fail_reason=lambda change, patch: "The applied change may cause existing nodes to be terminated hence requires "
    "the compute fleet to be stopped first",
    action_needed=UpdatePolicy.ACTIONS_NEEDED["pcluster_stop"],
    condition_checker=_check_min_count,
)

# Checks that the value of the parameter has not been decreased
UpdatePolicy.INCREASE_ONLY = UpdatePolicy(
    level=2,
    fail_reason=lambda change, patch: "Value of parameter '{0}' cannot be decreased".format(change.param_key),
    action_needed=lambda change, patch: "Set the value of parameter '{0}' to '{1}' or greater".format(
        change.param_key, change.old_value
    ),
    condition_checker=lambda change, patch: change.new_value >= change.old_value,
)

# Update supported only with all compute nodes down
UpdatePolicy.COMPUTE_FLEET_STOP = UpdatePolicy(
    level=10,
    fail_reason="All compute nodes must be stopped",
    action_needed=UpdatePolicy.ACTIONS_NEEDED["pcluster_stop"],
    condition_checker=lambda change, patch: not utils.cluster_has_running_capacity(patch.stack_name),
)

# Update supported only with head node down
UpdatePolicy.HEAD_NODE_STOP = UpdatePolicy(
    level=20,
    fail_reason="To perform this update action, the head node must be in a stopped state",
    action_needed=UpdatePolicy.ACTIONS_NEEDED["pcluster_stop"],
    condition_checker=lambda change, patch: utils.get_head_node_state(patch.stack_name) == "stopped",
)

# Expected Behavior:
# No bucket specified when create, no bucket specified when update: Display no diff, proceed with update
# For all other cases: Display diff and block, value will not be updated even if forced
UpdatePolicy.READ_ONLY_RESOURCE_BUCKET = UpdatePolicy(
    level=30,
    fail_reason=lambda change, patch: (
        "'{0}' parameter is a read_only parameter that cannot be updated. "
        "New value '{1}' will be ignored and old value '{2}' will be used if you force the update."
    ).format(
        change.param_key,
        change.new_value,
        change.old_value,
    ),
    action_needed=lambda change, patch: "Restore the value of parameter '{0}' to '{1}'".format(
        change.param_key, change.old_value
    ),
    condition_checker=_check_generated_bucket,
    # We don't want to show the change if allowed (e.g local value is empty)
    print_succeeded=False,
)

# Update effects are unknown.
# WARNING: This is the default value for all new configuration parameters. All parameters must be linked to a specific
# update policy instead of UNKNOWN to pass unit tests.
#
UpdatePolicy.UNKNOWN = UpdatePolicy(
    level=100,
    fail_reason="Update currently not supported",
    action_needed="Restore the previous parameter value for the unsupported changes.",
)

# Update not supported
UpdatePolicy.UNSUPPORTED = UpdatePolicy(
    level=1000,
    fail_reason=lambda change, patch: "Update actions are not currently supported for the '{0}' parameter".format(
        change.param_key
    ),
    action_needed=lambda change, patch: (
        "Restore '{0}' value to '{1}'".format(change.param_key, change.old_value)
        if change.old_value is not None
        else "Remove the parameter '{0}'".format(change.param_key)
    )
    + ". If you need this change, please consider creating a new cluster instead of updating the existing one.",
)
