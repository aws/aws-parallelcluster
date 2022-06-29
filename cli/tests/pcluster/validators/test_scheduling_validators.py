import pytest

from pcluster.constants import SUPPORTED_SCHEDULERS
from pcluster.validators.cluster_validators import SchedulerValidator
from pcluster.validators.common import FailureLevel
from tests.pcluster.validators.utils import assert_failure_level, assert_failure_messages


@pytest.mark.parametrize(
    "scheduler, expected_failure_level, expected_message",
    [
        ("slurm", None, None),
        ("awsbatch", None, None),
        (
            "plugin",
            FailureLevel.ERROR,
            f"plugin scheduler is not supported. Supported schedulers are: {', '.join(SUPPORTED_SCHEDULERS)}.",
        ),
    ],
)
def test_scheduler_validator(scheduler, expected_failure_level, expected_message):
    actual_failures = SchedulerValidator().execute(scheduler=scheduler)
    assert_failure_level(actual_failures, expected_failure_level)
    assert_failure_messages(actual_failures, expected_message)
