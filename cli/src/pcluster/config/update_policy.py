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

from pcluster.constants import DEFAULT_MAX_COUNT


class UpdatePolicy:
    """Describes the policy that rules the update of a configuration parameter."""

    class CheckResult(str, Enum):
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
    "shared_storage_change": "Shared Storage cannot be added or removed during a 'pcluster update-cluster' operation",
    "cookbook_update": lambda change, patch: (
        "Updating cookbook related parameter is not supported because it only "
        "applies updates to compute nodes. If you still want to proceed, first stop the compute fleet with the "
        "pcluster update-compute-fleet command and then run an update with the --force-update flag"
    ),
}

# Common action_needed messages
UpdatePolicy.ACTIONS_NEEDED = {
    "ebs_volume_update": "Follow the instructions at {0}#{1} to modify your volume from AWS Console.".format(
        "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/requesting-ebs-volume-modifications.html",
        "modify-ebs-volume",
    ),
    "pcluster_stop": lambda change, patch: "Stop the compute fleet with the pcluster update-compute-fleet command",
}

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
        patch.cluster.get_running_capacity()
    ),
    action_needed=UpdatePolicy.ACTIONS_NEEDED["pcluster_stop"],
    condition_checker=lambda change, patch: patch.cluster.get_running_capacity()
    <= patch.target_config["Scheduling"]["AwsBatchQueues"][0]["ComputeResources"][0]["MaxvCpus"],
)

# Checks resize of max_count
UpdatePolicy.MAX_COUNT = UpdatePolicy(
    level=1,
    fail_reason=lambda change, patch: "Shrinking a queue requires the compute fleet to be stopped first",
    action_needed=UpdatePolicy.ACTIONS_NEEDED["pcluster_stop"],
    condition_checker=lambda change, patch: not patch.cluster.has_running_capacity()
    or (change.new_value if change.new_value is not None else DEFAULT_MAX_COUNT)
    >= (change.old_value if change.old_value is not None else DEFAULT_MAX_COUNT),
)

# Update supported only with all compute nodes down
UpdatePolicy.COMPUTE_FLEET_STOP = UpdatePolicy(
    level=10,
    fail_reason="All compute nodes must be stopped",
    action_needed=UpdatePolicy.ACTIONS_NEEDED["pcluster_stop"],
    condition_checker=lambda change, patch: not patch.cluster.has_running_capacity(),
)

# Update supported only with head node down
UpdatePolicy.HEAD_NODE_STOP = UpdatePolicy(
    level=20,
    fail_reason="To perform this update action, the head node must be in a stopped state",
    action_needed=UpdatePolicy.ACTIONS_NEEDED["pcluster_stop"],
    condition_checker=lambda change, patch: patch.cluster.head_node_instance.state == "stopped",
)

# Expected Behavior:
# No bucket specified when create, no bucket specified when update: Display no diff, proceed with update
# For all other cases: Display diff and block, value will not be updated even if forced
UpdatePolicy.READ_ONLY_RESOURCE_BUCKET = UpdatePolicy(
    level=30,
    fail_reason=lambda change, patch: (
        "'{0}' parameter is a read only parameter that cannot be updated. "
        "New value '{1}' will be ignored and old value '{2}' will be used if you force the update."
    ).format(change.key, change.new_value, change.old_value),
    action_needed=lambda change, patch: f"Restore the value of parameter '{change.key}' to '{change.old_value}'",
    condition_checker=lambda change, patch: False,
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
    fail_reason=lambda change, patch: (f"Update actions are not currently supported for the '{change.key}' parameter"),
    action_needed=lambda change, patch: (
        f"Restore '{change.key}' value to '{change.old_value}'"
        if change.old_value is not None
        else "{0} the parameter '{1}'".format("Restore" if change.is_list else "Remove", change.key)
    )
    + ". If you need this change, please consider creating a new cluster instead of updating the existing one.",
)
