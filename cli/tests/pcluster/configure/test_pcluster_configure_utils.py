import pytest
from assertpy import assert_that

from pcluster.configure.utils import get_default_suggestion


@pytest.mark.parametrize(
    "parameter, options, expected_suggestion, expected_exception",
    [
        # For the parameters for which we want to have opinionated defaults, it
        # doesn't matter what options are passed in with them.
        ("Scheduler", None, "slurm", None),
        ("Scheduler", [], "slurm", None),
        ("Scheduler", ["sge", "torque", "awsbatch"], "slurm", None),
        ("Operating System", None, "alinux2", None),
        ("Operating System", [], "alinux2", None),
        ("Operating System", ["centos8", "centos7", "ubuntu1804"], "alinux2", None),
        # Ensure first item is selected from first nested list/tuple
        ("fake-parameter", [{"id": "a", "key2": "b"}, {"id": "c", "key3": "d"}], "a", None),
        ("fake-parameter", ({"id": "a", "key2": "b"}, {"id": "c", "key3": "d"}), "a", None),
        # Ensure first item is selected from flat lists/tuples
        ("fake-parameter", ["a", "b", "c", "d"], "a", None),
        ("fake-parameter", ("a", "b", "c", "d"), "a", None),
        # Ensure that empty string is returned if options isn't list/tuple
        ("fake-parameter", None, "", None),
        ("fake-parameter", "string", "", None),
        ("fake-parameter", 10, "", None),
        # tuples/lists are assumed to be non-empty
        ("fake-parameter", [], None, IndexError),
        ("fake-parameter", (), None, IndexError),
    ],
)
def test_get_default_suggestion(parameter, options, expected_suggestion, expected_exception):
    if expected_exception:
        with pytest.raises(expected_exception):
            get_default_suggestion(parameter, options)
    else:
        assert_that(get_default_suggestion(parameter, options)).is_equal_to(expected_suggestion)
