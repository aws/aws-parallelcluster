from aws_cdk import aws_budgets as budgets
from aws_cdk.core import Construct

from pcluster.config.cluster_config import BaseClusterConfig


class CostBudgets:
    """Create the budgets based on the configuration file."""

    def __init__(self, scope: Construct, cluster_config: BaseClusterConfig):
        self.cluster_config = cluster_config
        self.scope = scope

    def create_budgets(self):
        """Create the Cfn templates for the list of budgets."""
        budget_list = self.cluster_config.dev_settings.budgets
        cfn_budget_list = []
        for index, budget in enumerate(budget_list):

            budget_data = budgets.CfnBudget.BudgetDataProperty(
                budget_name=f"CfnBudget{self.cluster_config.cluster_name}" + str(index),
                budget_type="COST",
                time_unit=budget.time_unit,
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=budget.budget_limit.amount,
                    unit=budget.budget_limit.unit,
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

            notifications_with_subscribers = None

            if budget.notifications_with_subscribers is not None:

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

            budget_id = f"CfnBudget{self.cluster_config.cluster_name}" + str(index)
            cfn_budget = budgets.CfnBudget(
                self.scope, budget_id, budget=budget_data, notifications_with_subscribers=notifications_with_subscribers
            )

            cfn_budget_list.append(cfn_budget)

        return cfn_budget_list
