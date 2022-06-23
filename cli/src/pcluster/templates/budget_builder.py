from aws_cdk import aws_budgets as budgets
from aws_cdk.core import Construct

from pcluster.config.cluster_config import BaseClusterConfig


class CostBudgets:
    """Creates the budgets based on the configuration file"""

    def __init__(self, scope: Construct, cluster_config: BaseClusterConfig):
        self.cluster_config = cluster_config
        self.scope = scope

    def create_budgets(self):
        budget_list = self.cluster_config.dev_settings.budgets
        cfn_budget_list = []
        for index, budget in enumerate(budget_list):

            budget_data = budgets.CfnBudget.BudgetDataProperty(
                budget_name=budget.budget_name,
                budget_type="COST",
                time_unit=budget.time_unit,
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=budget.budget_limit.amount,
                    unit=budget.budget_limit.unit,
                ),

                cost_types=budgets.CfnBudget.CostTypesProperty(
                    include_credit=budget.include_credit,
                    include_discount=budget.include_discount,
                    include_other_subscription=budget.include_other_subscription,
                    include_recurring=budget.include_recurring,
                    include_refund=budget.include_refund,
                    include_subscription=budget.include_subscription,
                    include_support=budget.include_support,
                    include_tax=budget.include_tax,
                    include_upfront=budget.include_up_front,
                    use_amortized=budget.use_amortized,
                    use_blended=budget.use_blended,
                ),

                cost_filters=(
                    budget.cost_filters if budget.budget_category == 'custom' else (
                        {"TagKeyValue": [f'user:parallelcluster:cluster-name${self.cluster_config.cluster_name}']}
                        if budget.budget_category == 'cluster' else (
                            {"TagKeyValue": [f"user:parallelcluster:queue-name${budget.queue_name}"]}
                        )
                    )
                )
            )

            notifications_with_subscribers = None

            if budget.notifications_with_subscribers is not None:

                notifications_with_subscribers = []

                for single_notification in budget.notifications_with_subscribers:
                    notifications_with_subscribers.append(
                        budgets.CfnBudget.NotificationWithSubscribersProperty(
                            notification=budgets.CfnBudget.NotificationProperty(
                                comparison_operator=single_notification.comparison_operator,
                                notification_type=single_notification.notification_type,
                                threshold_type=single_notification.threshold_type,
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

            budget_id = f"CfnBudget-cluster:{self.cluster_config.cluster_name}" + str(index)
            cfn_budget = budgets.CfnBudget(
                self.scope, budget_id, budget=budget_data, notifications_with_subscribers=notifications_with_subscribers
            )

            cfn_budget_list.append(cfn_budget)

        return cfn_budget_list
