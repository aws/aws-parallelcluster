# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import boto3
import pytest
from assertpy import assert_that


@pytest.mark.usefixtures("os", "instance", "scheduler")
def test_update_budget_properties(pcluster_config_reader, clusters_factory, test_datadir, region):
    # Get the account id to check for the created budget
    sts_client = boto3.client("sts")
    account_id = sts_client.get_caller_identity().get("Account")
    budget_client = boto3.client("budgets")

    # Create the initial cluster without a budget definition
    init_config_file = pcluster_config_reader(config_file="no_budgets.yaml")
    cluster = clusters_factory(init_config_file)

    # Add a budget, verify that it is added, then delete it and check it was successfully deleted
    _test_create_and_delete_budgets(
        cluster, init_config_file, budget_client, account_id, region, pcluster_config_reader
    )

    # Add one budget of each BudgetCategory, update them, and check that the fields match the expected values
    _test_update_cluster_and_check_fields(cluster, budget_client, account_id, region, pcluster_config_reader)


def _test_create_and_delete_budgets(
    cluster, init_config_file, budget_client, account_id, region, pcluster_config_reader
):
    # Update the cluster to add a budget
    new_config_file = pcluster_config_reader(config_file="budget_with_notifications.yaml")
    cluster.update(str(new_config_file), force_update="true")

    # Try to describe the budget created by the cluster
    budget_name_beginning = f"{cluster.name}-0-{region}"
    budgets_description = budget_client.describe_budgets(AccountId=account_id)["Budgets"]
    assert_that(
        any([budget["BudgetName"].startswith(budget_name_beginning) for budget in budgets_description])
    ).is_true()

    # Update the cluster again with the initial file, removing the budget
    cluster.update(str(init_config_file), force_update="true")

    # Try to describe the budget again (should fail this time)
    budgets_description = budget_client.describe_budgets(AccountId=account_id)["Budgets"]
    assert_that(
        any([budget["BudgetName"].startswith(budget_name_beginning) for budget in budgets_description])
    ).is_false()


def _test_update_cluster_and_check_fields(cluster, budget_client, account_id, region, pcluster_config_reader):
    # Update cluster to have 3 budgets (one of each BudgetCategory)
    add_multiple_budgets_config_file = pcluster_config_reader(config_file="all_budget_categories.yaml")
    cluster.update(str(add_multiple_budgets_config_file), force_update="true")

    # Update the cluster to change the budget properties
    update_multiple_budgets_config_file = pcluster_config_reader(config_file="all_budget_categories_updated.yaml")
    cluster.update(str(update_multiple_budgets_config_file), force_update="true")

    # The budgets from the updated configuration
    budget_list = cluster.config["DevSettings"]["Budgets"]
    custom_budget, cluster_budget, queue_budget = budget_list[0], budget_list[1], budget_list[2]

    budget_description = budget_client.describe_budgets(AccountId=account_id)["Budgets"]

    # The expected budget names (without the hash), based on budget_builder.py
    custom_budget_name_short = f"{cluster.name}-0-custom-{region}"
    cluster_budget_name_short = f"{cluster.name}-1-{region}"
    queue_budget_name_short = f"{cluster.name}-2-queue1-{region}"

    # Look for the full names
    for budget in budget_description:
        name = budget["BudgetName"]
        if name.startswith(custom_budget_name_short):
            custom_budget_name = name
            custom_budget_amount = budget["BudgetLimit"]["Amount"]
        elif name.startswith(cluster_budget_name_short):
            cluster_budget_name = name
            cluster_budget_amount = budget["BudgetLimit"]["Amount"]
        elif name.startswith(queue_budget_name_short):
            queue_budget_name = name
            queue_budget_amount = budget["BudgetLimit"]["Amount"]

    # Check updated budget limits
    assert_that(custom_budget_amount).is_equal_to(str(custom_budget["BudgetLimit"]["Amount"]))
    assert_that(cluster_budget_amount).is_equal_to(str(cluster_budget["BudgetLimit"]["Amount"]))
    assert_that(queue_budget_amount).is_equal_to(str(queue_budget["BudgetLimit"]["Amount"]))

    # Check the updated notification fields
    _check_notification_fields(custom_budget, custom_budget_name, account_id, budget_client)
    _check_notification_fields(cluster_budget, cluster_budget_name, account_id, budget_client)
    _check_notification_fields(queue_budget, queue_budget_name, account_id, budget_client)


def _check_notification_fields(expected_budget, budget_name, account_id, budget_client):
    """Check the basic notification fields."""
    # Each budget in this test's config file has only one notification. Otherwise, comparing them would be difficult
    described_notification = budget_client.describe_notifications_for_budget(
        AccountId=account_id,
        BudgetName=budget_name,
    )["Notifications"][0]
    expected_notification = expected_budget["NotificationsWithSubscribers"][0]["Notification"]

    # Compare the expected fields with the described fields
    if expected_notification.get("NotificationType"):
        assert_that(described_notification["NotificationType"]).is_equal_to(expected_notification["NotificationType"])
    if expected_notification.get("ComparisonOperator"):
        assert_that(described_notification["ComparisonOperator"]).is_equal_to(
            expected_notification["ComparisonOperator"]
        )
    if expected_notification.get("ThresholdType"):
        assert_that(described_notification["ThresholdType"]).is_equal_to(expected_notification["ThresholdType"])
    assert_that(str(described_notification["Threshold"])).is_equal_to(str(expected_notification["Threshold"]))

    # Get the notification subscribers
    notification_subscribers_description = budget_client.describe_subscribers_for_notification(
        AccountId=account_id,
        BudgetName=budget_name,
        Notification=described_notification,
    )

    # Each notification in this test's config will only have one subscriber. Otherwise, comparing them would be hard
    described_subscriber = notification_subscribers_description["Subscribers"][0]
    expected_subscriber = expected_budget["NotificationsWithSubscribers"][0]["Subscribers"][0]

    # Compare the subscriber with the expected subscriber
    assert_that(described_subscriber["Address"]).is_equal_to(expected_subscriber["Address"])
    assert_that(described_subscriber["SubscriptionType"]).is_equal_to(expected_subscriber["SubscriptionType"])
