"""This module provides unit tests for the functions in the pcluster.delete module."""

from collections import namedtuple

import pytest
from assertpy import assert_that

import pcluster.utils as utils
from common.boto3.common import AWSClientError
from pcluster.models.cluster import Cluster, ClusterActionError, ClusterStack

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
    "keep_logs,persist_called,terminate_instances_called",
    [
        (False, False, True),
        (False, False, True),
        (True, True, True),
    ],
)
def test_delete(mocker, keep_logs, persist_called, terminate_instances_called):
    """Verify that Cluster.delete behaves as expected."""
    mocker.patch("pcluster.models.cluster.Stack.__init__", return_value=None)
    mocker.patch("pcluster.models.cluster.Stack.delete")
    cluster_stack = ClusterStack(FAKE_STACK_NAME)
    cluster_stack.name = FAKE_STACK_NAME
    persist_cloudwatch_log_groups_mock = mocker.patch.object(cluster_stack, "_persist_cloudwatch_log_groups")

    mocker.patch("pcluster.models.cluster.Cluster.__init__", return_value=None)
    cluster = Cluster(FAKE_CLUSTER_NAME)
    cluster.stack = cluster_stack
    terminate_nodes_mock = mocker.patch.object(cluster, "_terminate_nodes")

    cluster.delete(keep_logs)

    assert_that(persist_cloudwatch_log_groups_mock.called).is_equal_to(persist_called)
    assert_that(terminate_nodes_mock.call_count).is_equal_to(1 if terminate_instances_called else 0)


@pytest.mark.parametrize(
    "template, expected_retain, fail_on_persist",
    [
        ({}, False, False),
        (
            {"Resources": {"key": {"DeletionPolicy": "Retain"}}},
            True,
            False,
        ),
        (
            {"Resources": {"key": {"DeletionPolicy": "Retain"}}},
            True,
            True,
        ),
        (
            {"Resources": {"key": {"DeletionPolicy": "Don't Retain"}}},
            False,
            False,
        ),
        (
            {"Resources": {"key": {"DeletionPolicy": "Delete"}}},
            False,
            False,
        ),
    ],
)
def test_persist_cloudwatch_log_groups(mocker, caplog, template, expected_retain, fail_on_persist):
    """Verify that commands._persist_cloudwatch_log_groups behaves as expected."""
    mocker.patch("pcluster.models.cluster.Stack.__init__", return_value=None)
    cluster_stack = ClusterStack(FAKE_STACK_NAME)
    cluster_stack.name = FAKE_STACK_NAME
    cluster_stack._stack_data = {"TemplateBody": template}

    client_error = AWSClientError("function", "Generic error.")
    update_template_mock = mocker.patch.object(
        cluster_stack, "_update_template", side_effect=client_error if fail_on_persist else None
    )

    if expected_retain:
        keys = ["key"]
    else:
        keys = []
    get_unretained_cw_log_group_resource_keys_mock = mocker.patch.object(
        cluster_stack, "_get_unretained_cw_log_group_resource_keys", return_value=keys
    )

    if fail_on_persist:
        with pytest.raises(ClusterActionError) as e:
            cluster_stack._persist_cloudwatch_log_groups()
        assert_that(str(e)).contains("Unable to persist logs")
    else:
        cluster_stack._persist_cloudwatch_log_groups()

    assert_that(get_unretained_cw_log_group_resource_keys_mock.call_count).is_equal_to(1)
    assert_that(update_template_mock.call_count).is_equal_to(1 if expected_retain else 0)


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
    mocker.patch("pcluster.models.cluster.Stack.__init__", return_value=None)
    cluster_stack = ClusterStack(FAKE_STACK_NAME)
    cluster_stack.name = FAKE_STACK_NAME
    cluster_stack._stack_data = {"TemplateBody": template}
    update_stack_template_mock = mocker.patch.object(cluster_stack, "_update_template")

    if "Resources" not in template:
        expected_error_message = "Resources"
    elif "key" not in template.get("Resources"):
        expected_error_message = "key"
    else:
        expected_error_message = None

    if expected_error_message:
        with pytest.raises(KeyError, match=expected_error_message):
            cluster_stack._persist_stack_resources(["key"])
        assert_that(update_stack_template_mock.called).is_false()
    else:
        cluster_stack._persist_stack_resources(["key"])
        assert_that(update_stack_template_mock.called).is_true()
        assert_that(cluster_stack.template["Resources"]["key"]["DeletionPolicy"]).is_equal_to("Retain")


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
def test_get_unretained_cw_log_group_resource_keys(mocker, template, expected_return):
    """Verify that commands._get_unretained_cw_log_group_resource_keys behaves as expected."""
    mocker.patch("pcluster.models.cluster.Stack.__init__", return_value=None)
    cluster_stack = ClusterStack(FAKE_STACK_NAME)
    cluster_stack.name = FAKE_STACK_NAME
    cluster_stack._stack_data = {"TemplateBody": template}

    observed_return = cluster_stack._get_unretained_cw_log_group_resource_keys()
    assert_that(observed_return).is_equal_to(expected_return)
