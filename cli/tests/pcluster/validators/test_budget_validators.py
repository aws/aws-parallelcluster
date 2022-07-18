import pytest

from pcluster.validators.budget_validators import BudgetFilterTagValidator
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "budget_category, tag_status, expected_message",
    [
        (
            "cluster",
            "NotFound",
            "Error: creating a budget of BudgetCategory: cluster was not possible. "
            "The tag: parallelcluster:cluster-name was not found in your account.",
        ),
        (
            "cluster",
            "Inactive",
            "Error: creating a budget of BudgetCategory: cluster was not possible. "
            "The tag: parallelcluster:cluster-name is inactive. Activate it and try again.",
        ),
        (
            "queue",
            "NotFound",
            "Error: creating a budget of BudgetCategory: queue was not possible. "
            "The tag: parallelcluster:queue-name was not found in your account.",
        ),
        ("cluster", "Active", None),
        (
            "queue",
            "Inactive",
            "Error: creating a budget of BudgetCategory: queue was not possible. "
            "The tag: parallelcluster:queue-name is inactive. Activate it and try again.",
        ),
        ("custom", "NotFound", None),
        ("custom", "Active", None),
    ],
)
def test_budget_filter_tag_validator(mocker, budget_category, tag_status, expected_message):
    budget_category_to_tag_key_map = {
        "cluster": "parallelcluster:cluster-name",
        "queue": "parallelcluster:queue-name",
        "custom": "fakeTag",
    }
    tag_key = budget_category_to_tag_key_map.get(budget_category)
    mocker.patch(
        "pcluster.aws.cost_explorer.CostExplorerClient.list_cost_allocation_tags",
        return_value={"CostAllocationTags": [{"TagKey": tag_key, "Status": tag_status}]},
    )
    actual_failures = BudgetFilterTagValidator().execute(budget_category=budget_category)
    assert_failure_messages(actual_failures, expected_message)
