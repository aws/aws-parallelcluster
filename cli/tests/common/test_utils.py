import pytest
from assertpy import assert_that

from common.utils import validate_json_format


@pytest.mark.parametrize(
    "data, expected_value",
    [
        ('{"cluster": {"cfn_scheduler_slots": "cores"}}', True),
        ('{"cluster"}: {"cfn_scheduler_slots": "cores"}}', False),
    ],
)
def test_validate_json_format(data, expected_value):
    assert_that(validate_json_format(data)).is_equal_to(expected_value)
