"""This module provides unit tests for the functions in the pcluster.delete module."""

from collections import namedtuple

import pytest

import pcluster.commands as commands
from assertpy import assert_that

FakePdeleteArgs = namedtuple("FakePdeleteArgs", "cluster_name config_file nowait keep_logs region")


def get_fake_pdelete_args(cluster_name="cluster_name", config_file=None, nowait=False, keep_logs=False, region=None):
    """Get a FakePdeleteArgs instance, with None used for any parameters not specified."""
    return FakePdeleteArgs(
        cluster_name=cluster_name, config_file=config_file, nowait=nowait, keep_logs=keep_logs, region=region
    )


@pytest.mark.parametrize(
    "keep_logs,stack_exists,warn_call_count,persist_called,delete_called",
    [
        (True, False, 2, False, False),
        (False, False, 1, False, False),
        (False, True, 0, False, True),
        (True, True, 0, True, True),
    ],
)
def test_delete(mocker, keep_logs, stack_exists, warn_call_count, persist_called, delete_called):
    """Verify that commands.delete behaves as expected."""
    mocker.patch("pcluster.commands.utils.stack_exists").return_value = stack_exists
    mocker.patch("pcluster.commands._persist_cloudwatch_log_group")
    mocker.patch("pcluster.commands._delete_cluster")
    mocker.patch("pcluster.commands.utils.warn")
    mocker.patch("pcluster.commands.PclusterConfig")
    args = get_fake_pdelete_args(keep_logs=keep_logs)

    if not stack_exists:
        with pytest.raises(SystemExit) as sysexit:
            commands.delete(args)
        assert_that(sysexit.value.code).is_equal_to(0)
    else:
        commands.delete(args)

    assert_that(commands.utils.warn.call_count).is_equal_to(warn_call_count)
    if warn_call_count > 0:
        commands.utils.warn.assert_called_with("Cluster {0} has already been deleted.".format(args.cluster_name))

    assert_that(commands._persist_cloudwatch_log_group.called).is_equal_to(persist_called)
    if persist_called:
        commands._persist_cloudwatch_log_group.assert_called_with(
            args.cluster_name, commands.PclusterConfig(args.cluster_name)
        )

    assert_that(commands._delete_cluster.called).is_equal_to(delete_called)
    if delete_called:
        commands._delete_cluster.assert_called_with(args.cluster_name, args.nowait)


@pytest.mark.parametrize(
    "feature_enabled,substack,substack_template",
    [
        (False, None, None),
        (True, {"StackName": "stack_name"}, {"Resources": {"CloudWatchLogGroup": {"DeletionPolicy": "Retain"}}}),
        (
            True,
            {"StackName": "stack_name"},
            {"Resources": {"CloudWatchLogGroup": {"DeletionPolicy": "NotRetain"}}, "Parameters": "FakeParameters"},
        ),
    ],
)
def test_persist_cloudwatch_log_group(mocker, feature_enabled, substack, substack_template):
    """Verify that commands._persist_cloudwatch_log_group behaves as expected."""
    cluster_name = "cluster_name"
    pcluster_config = mocker.Mock()
    pcluster_config.get_section.return_value.get_param_value.return_value = feature_enabled

    mocker.patch("pcluster.commands.utils.warn")
    mocker.patch("pcluster.commands.utils.get_cloudwatch_logs_substack").return_value = substack
    mocker.patch("pcluster.commands.utils.get_stack_template").return_value = substack_template
    mocker.patch("pcluster.commands.utils.update_stack_template")
    if substack_template:
        orig_retain = substack_template.get("Resources").get("CloudWatchLogGroup").get("DeletionPolicy") == "Retain"
    else:
        orig_retain = False

    commands._persist_cloudwatch_log_group(cluster_name, pcluster_config)

    if not feature_enabled:
        commands.utils.warn.assert_called_with("CloudWatch logging is not enabled for cluster {0}".format(cluster_name))

    if substack:
        commands.utils.get_cloudwatch_logs_substack.assert_called_with(cluster_name)

    if substack_template:
        commands.utils.get_stack_template.assert_called_with(substack.get("StackName"))
        if orig_retain:
            assert_that(commands.utils.update_stack_template.called).is_false()
        else:
            commands.utils.update_stack_template.assert_called_with(
                substack.get("StackName"), substack_template, substack.get("Parameters")
            )
