from aws_cdk import aws_budgets as budgets
from aws_cdk.core import Construct

from pcluster.config.cluster_config import BaseClusterConfig


class CostBudgets:
    """Create the budgets based on the configuration file."""

    def __init__(self, scope: Construct, cluster_config: BaseClusterConfig):
        self.cluster_config = cluster_config
        self.scope = scope
        self._create_budgets()

    def _create_budgets(self):
        """Create the Cfn templates for the list of budgets."""
        budget_list = self.cluster_config.dev_settings.budgets
        cfn_budget_list = []

        for index, budget in enumerate(budget_list):
            cfn_budget = self._add_parameters(budget, index)
            cfn_budget_list.append(cfn_budget)

        return cfn_budget_list

    def _add_parameters(self, budget, index):
        """Add each budget's parameters."""
        if budget.budget_category == "queue":
            name = f"{self.cluster_config.cluster_name}-{index}-{budget.queue_name}-{self.cluster_config.region}"
        elif budget.budget_category == "cluster":
            name = f"{self.cluster_config.cluster_name}-{index}-{self.cluster_config.region}"
        else:
            name = f"{self.cluster_config.cluster_name}-{index}-custom-{self.cluster_config.region}"

        budget_data = budgets.CfnBudget.BudgetDataProperty(
            budget_name=name,
            budget_type="COST",
            time_unit=budget.time_unit,
            budget_limit=budgets.CfnBudget.SpendProperty(
                amount=budget.budget_limit.amount, unit=budget.budget_limit.unit
            ),
            cost_filters=(
                budget.cost_filters
                if budget.budget_category == "custom"
                else (
                    {"TagKeyValue": [f"user:parallelcluster:cluster-name${self.cluster_config.cluster_name}"]}
                    if budget.budget_category == "cluster"
                    else ({"TagKeyValue": [f"user:parallelcluster:queue-name${budget.queue_name}"]})
                )
            ),
        )
        notifications_with_subscribers = (
            add_budget_notifications(budget) if budget.notifications_with_subscribers else None
        )
        budget_id = f"Budget{str(index)}"
        cfn_budget = budgets.CfnBudget(
            self.scope, budget_id, budget=budget_data, notifications_with_subscribers=notifications_with_subscribers
        )
        return cfn_budget


def add_budget_notifications(budget):
    """Create the notifications with subscribers for each budget."""
    notifications_with_subscribers = []
    for single_notification in budget.notifications_with_subscribers:
        notifications_with_subscribers.append(
            budgets.CfnBudget.NotificationWithSubscribersProperty(
                notification=budgets.CfnBudget.NotificationProperty(
                    comparison_operator=single_notification.notification.comparison_operator,
                    notification_type=single_notification.notification.notification_type,
                    threshold_type=single_notification.notification.threshold_type,
                    threshold=single_notification.notification.threshold,
                ),
                subscribers=[
                    budgets.CfnBudget.SubscriberProperty(
                        address=subscriber.address,
                        subscription_type=subscriber.subscription_type,
                    )
                    for subscriber in single_notification.subscribers
                ],
            )
        )

    return notifications_with_subscribers
