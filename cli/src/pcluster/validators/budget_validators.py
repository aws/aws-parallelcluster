from pcluster.aws.aws_api import AWSApi
from pcluster.validators.common import FailureLevel, Validator


class BudgetFilterTagValidator(Validator):
    """
    Budget CostFilters Tag validator.

    Validate if the tag used for the filter is active under the user's account.
    """

    def _validate(self, budget_category):
        budget_category_to_tag_key_map = {
            "cluster": "parallelcluster:cluster-name",
            "queue": "parallelcluster:queue-name",
        }
        self.tag_key = budget_category_to_tag_key_map.get(budget_category)
        if self.tag_key is None:
            return

        # Check if the tag is active
        tag_status = self._get_tag_status()

        if tag_status == "Inactive":
            self._add_failure(
                (
                    f"Error: creating a budget of BudgetCategory: {budget_category} was not possible. "
                    f"The tag: {self.tag_key} is inactive. Activate it and try again."
                ),
                FailureLevel.ERROR,
            )

        elif tag_status == "NotFound":
            self._add_failure(
                (
                    f"Error: creating a budget of BudgetCategory: {budget_category} was not possible. "
                    f"The tag: {self.tag_key} was not found in your account."
                ),
                FailureLevel.ERROR,
            )

    def _get_tag_status(self):
        client_tags = AWSApi.instance().cost_explorer.list_cost_allocation_tags()["CostAllocationTags"]
        return next((tag["Status"] for tag in client_tags if tag["TagKey"] == self.tag_key), "NotFound")


class TriggerFleetStopValidator(Validator):
    """
    Validate that trigger_fleet_stop is only specified if budget_category = cluster.

    This is not in schema validators so that it can be skipped, if necessary.
    """

    def _validate(self, budget_category, notifications_with_subscribers):
        if budget_category != "cluster" and any(
            (not notification_with_subscribers.is_implied("trigger_fleet_stop"))
            for notification_with_subscribers in notifications_with_subscribers
        ):
            self._add_failure(
                "TriggerFleetStop can only be specified when BudgetCategory is set to cluster.",
                FailureLevel.ERROR,
            )
