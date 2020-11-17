"""This module provides unit tests for the functions in the pcluster.delete module."""

from collections import namedtuple

import pytest
from assertpy import assert_that
from botocore.exceptions import ClientError

import pcluster.utils as utils
from pcluster.cli_commands.delete import (
    _get_unretained_cw_log_group_resource_keys,
    _persist_cloudwatch_log_groups,
    _persist_stack_resources,
    delete,
)

FakePdeleteArgs = namedtuple("FakePdeleteArgs", "cluster_name config_file nowait keep_logs region")
FAKE_CLUSTER_NAME = "cluster_name"
FAKE_STACK_NAME = utils.get_stack_name(FAKE_CLUSTER_NAME)
LOG_GROUP_TYPE = "AWS::Logs::LogGroup"


def get_fake_pdelete_args(cluster_name="cluster_name", config_file=None, nowait=False, keep_logs=False, region=None):
    """Get a FakePdeleteArgs instance, with None used for any parameters not specified."""
    return FakePdeleteArgs(
        cluster_name=cluster_name, config_file=config_file, nowait=nowait, keep_logs=keep_logs, region=region
    )


@pytest.mark.parametrize(
    "keep_logs,stack_exists,warn_call_count,persist_called,delete_called,terminate_instances_called",
    [
        (True, False, 2, False, False, True),
        (False, False, 1, False, False, True),
        (False, True, 0, False, True, False),
        (True, True, 0, True, True, False),
    ],
)
def test_delete(
    mocker, keep_logs, stack_exists, warn_call_count, persist_called, delete_called, terminate_instances_called
):
    """Verify that commands.delete behaves as expected."""
    mocker.patch("pcluster.commands.utils.stack_exists").return_value = stack_exists
    persist_cloudwatch_log_groups_mock = mocker.patch("pcluster.cli_commands.delete._persist_cloudwatch_log_groups")
    delete_cluster_mock = mocker.patch("pcluster.cli_commands.delete._delete_cluster")
    warn_mock = mocker.patch("pcluster.commands.utils.warn")
    init_aws_mock = mocker.patch("pcluster.commands.PclusterConfig.init_aws")
    terminate_cluster_nodes_mock = mocker.patch("pcluster.cli_commands.delete._terminate_cluster_nodes")
    args = get_fake_pdelete_args(keep_logs=keep_logs)

    if not stack_exists:
        with pytest.raises(SystemExit) as sysexit:
            delete(args)
        assert_that(sysexit.value.code).is_equal_to(0)
    else:
        delete(args)

    init_aws_mock.called_with(args.config_file)

    assert_that(warn_mock.call_count).is_equal_to(warn_call_count)
    if warn_call_count > 0:
        warn_mock.assert_called_with(
            "Cluster {0} has already been deleted or does not exist.".format(args.cluster_name)
        )

    assert_that(persist_cloudwatch_log_groups_mock.called).is_equal_to(persist_called)
    if persist_called:
        persist_cloudwatch_log_groups_mock.assert_called_with(args.cluster_name)

    assert_that(delete_cluster_mock.called).is_equal_to(delete_called)
    if delete_called:
        delete_cluster_mock.assert_called_with(args.cluster_name, args.nowait)

    if terminate_instances_called:
        terminate_cluster_nodes_mock.assert_called_with(FAKE_STACK_NAME)


@pytest.mark.parametrize(
    "stacks, template, expected_retain, fail_on_persist",
    [
        ([], {}, False, False),
        (
            [{"StackName": FAKE_STACK_NAME}, {"StackName": "cluster-CloudWatchLogsSubstack-1395RJR972JUT"}],
            {"Resources": {"key": {"DeletionPolicy": "Retain"}}},
            True,
            False,
        ),
        (
            [{"StackName": FAKE_STACK_NAME}, {"StackName": "cluster-CloudWatchLogsSubstack-1395RJR972JUT"}],
            {"Resources": {"key": {"DeletionPolicy": "Retain"}}},
            True,
            True,
        ),
        (
            [{"StackName": FAKE_STACK_NAME}, {"StackName": "cluster-CloudWatchLogsSubstack-1395RJR972JUT"}],
            {"Resources": {"key": {"DeletionPolicy": "Don't Retain"}}},
            False,
            False,
        ),
        (
            [{"StackName": FAKE_STACK_NAME}, {"StackName": "cluster-CloudWatchLogsSubstack-1395RJR972JUT"}],
            {"Resources": {"key": {"DeletionPolicy": "Delete"}}},
            False,
            False,
        ),
    ],
)
def test_persist_cloudwatch_log_groups(mocker, caplog, stacks, template, expected_retain, fail_on_persist):
    """Verify that commands._persist_cloudwatch_log_groups behaves as expected."""
    get_cluster_substacks_mock = mocker.patch("pcluster.commands.utils.get_cluster_substacks", return_value=stacks)
    get_stack_template_mock = mocker.patch("pcluster.commands.utils.get_stack_template", return_value=template)
    client_error = ClientError({"Error": {"Code": "error"}}, "failed")
    update_stack_template_mock = mocker.patch(
        "pcluster.commands.utils.update_stack_template", side_effect=client_error if fail_on_persist else None
    )
    if expected_retain:
        keys = ["key"]
    else:
        keys = []
    has_cw_substack = any("CloudWatchLogsSubstack" in stack.get("StackName") for stack in stacks)
    get_unretained_cw_log_group_resource_keys_mock = mocker.patch(
        "pcluster.cli_commands.delete._get_unretained_cw_log_group_resource_keys", return_value=keys
    )

    if fail_on_persist:
        with pytest.raises(SystemExit) as e:
            _persist_cloudwatch_log_groups(FAKE_CLUSTER_NAME)
        assert_that(e.value.code).contains("Unable to persist logs")
        assert_that(e.type).is_equal_to(SystemExit)
    else:
        _persist_cloudwatch_log_groups(FAKE_CLUSTER_NAME)

    get_cluster_substacks_mock.assert_called_with(FAKE_CLUSTER_NAME)
    assert_that(get_stack_template_mock.call_count).is_equal_to(1 if has_cw_substack else 0)
    assert_that(get_unretained_cw_log_group_resource_keys_mock.call_count).is_equal_to(1 if has_cw_substack else 0)
    assert_that(update_stack_template_mock.call_count).is_equal_to(1 if expected_retain else 0)


@pytest.mark.parametrize(
    "template",
    [
        {},
        {"Resources": {}},
        {"Resources": {"key": {}}},
        {"Resources": {"key": {"DeletionPolicy": "Don't Retain"}}},
        {"Resources": {"key": {"DeletionPolicy": "Delete"}}},
        {"Resources": {"key": {"DeletionPolicy": "Retain"}}},  # Note update_stack_template still called for this
    ],
)
def test_persist_stack_resources(mocker, template):
    """Verify that commands._persist_stack_resources behaves as expected."""
    update_stack_template_mock = mocker.patch("pcluster.commands.utils.update_stack_template")
    stack = {"StackName": FAKE_STACK_NAME, "Parameters": {"Some Key": "Some Values"}}

    if "Resources" not in template:
        expected_error_message = "Resources"
    elif "key" not in template.get("Resources"):
        expected_error_message = "key"
    else:
        expected_error_message = None

    if expected_error_message:
        with pytest.raises(KeyError, match=expected_error_message):
            _persist_stack_resources(stack, template, ["key"])
        assert_that(utils.update_stack_template.called).is_false()
    else:
        _persist_stack_resources(stack, template, ["key"])
        update_stack_template_mock.assert_called_with(stack.get("StackName"), template, stack.get("Parameters"))
        assert_that(template["Resources"]["key"]["DeletionPolicy"]).is_equal_to("Retain")


@pytest.mark.parametrize(
    "template,expected_return",
    [
        ({}, []),
        ({"Resources": {}}, []),
        ({"Resources": {"ResourceOne": {"Type": LOG_GROUP_TYPE, "DeletionPolicy": "Retain"}}}, []),
        ({"Resources": {"ResourceOne": {"Type": LOG_GROUP_TYPE, "DeletionPolicy": "NotRetain"}}}, ["ResourceOne"]),
        ({"Resources": {"ResourceOne": {"Type": LOG_GROUP_TYPE, "DeletionPolicy": "Delete"}}}, ["ResourceOne"]),
    ],
)
def test_get_unretained_cw_log_group_resource_keys(template, expected_return):
    """Verify that commands._get_unretained_cw_log_group_resource_keys behaves as expected."""
    observed_return = _get_unretained_cw_log_group_resource_keys(template)
    assert_that(observed_return).is_equal_to(expected_return)
