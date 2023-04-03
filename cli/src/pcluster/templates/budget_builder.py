# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from aws_cdk import aws_budgets as budgets
from constructs import Construct

from pcluster.config.cluster_config import BaseClusterConfig


class CostBudgets:
    """Create the budgets based on the configuration file."""

    def __init__(self, scope: Construct, cluster_config: BaseClusterConfig):
        self.cluster_config = cluster_config
        self.scope = scope
        self._create_budgets()

    def _create_budgets(self):
        """Create the Cfn templates for the list of budgets."""
        budget_list = self.cluster_config.budgets
        cfn_budget_list = []

        for budget in budget_list:
            cfn_budget = self._add_parameters(budget)
            cfn_budget_list.append(cfn_budget)

        return cfn_budget_list

    def _add_parameters(self, budget):
        """Add each budget's parameters."""
        cost_filters = {"TagKeyValue": [f"{tag.key}${tag.value}" for tag in budget.tags]}
        unit = "CNY" if self.cluster_config.region.startswith("cn") else "USD"
        budget_data = budgets.CfnBudget.BudgetDataProperty(
            budget_type="COST",
            time_unit=budget.time_unit,
            time_period=budgets.CfnBudget.TimePeriodProperty(start=budget.time_period_start),
            budget_limit=budgets.CfnBudget.SpendProperty(amount=budget.budget_limit_amount, unit=unit),
            cost_filters=cost_filters,
        )
        notifications_with_subscribers = (
            add_budget_notifications(budget) if budget.notifications_with_subscribers else None
        )
        budget_id = budget.name
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
                    comparison_operator="GREATER_THAN",
                    notification_type=single_notification.notification.notification_type,
                    threshold_type="PERCENTAGE",
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
