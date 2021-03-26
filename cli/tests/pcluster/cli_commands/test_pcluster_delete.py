"""This module provides unit tests for the functions in the pcluster.delete module."""
import os
from collections import namedtuple

import pytest
from assertpy import assert_that

from common.boto3.common import AWSClientError
from pcluster.models.cluster import ClusterActionError, ClusterStack
from tests.pcluster.models.cluster_dummy_model import mock_bucket, mock_bucket_object_utils, mock_bucket_utils
from tests.pcluster.test_utils import dummy_cluster

FakePdeleteArgs = namedtuple("FakePdeleteArgs", "cluster_name config_file nowait keep_logs region")
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
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    mocker.patch("common.boto3.cfn.CfnClient.describe_stack")
    mocker.patch("common.boto3.cfn.CfnClient.delete_stack")
    cluster = dummy_cluster()
    persist_cloudwatch_log_groups_mock = mocker.patch.object(cluster, "_persist_cloudwatch_log_groups")
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
    stack = _mock_bucket_property(mocker)
    cluster = dummy_cluster(stack=stack)
    template_property_mock = mocker.PropertyMock(return_value=template)
    mocker.patch("pcluster.models.cluster.ClusterStack.template", new_callable=template_property_mock)

    client_error = AWSClientError("function", "Generic error.")
    update_template_mock = mocker.patch.object(
        cluster.stack, "update_template", side_effect=client_error if fail_on_persist else None
    )
    mocker.patch("common.boto3.cfn.CfnClient.update_stack_from_url")
    mock_bucket(mocker)
    mock_bucket_utils(mocker)
    mock_bucket_object_utils(mocker)

    if expected_retain:
        keys = ["key"]
    else:
        keys = []
    get_unretained_cw_log_group_resource_keys_mock = mocker.patch.object(
        cluster, "_get_unretained_cw_log_group_resource_keys", return_value=keys
    )

    if fail_on_persist:
        with pytest.raises(ClusterActionError) as e:
            cluster._persist_cloudwatch_log_groups()
        assert_that(str(e)).contains("Unable to persist logs")
    else:
        cluster._persist_cloudwatch_log_groups()

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
    stack = _mock_bucket_property(mocker)
    cluster = dummy_cluster(stack=stack)
    template_property_mock = mocker.PropertyMock(return_value=template)
    mocker.patch("pcluster.models.cluster.ClusterStack.template", new_callable=template_property_mock)
    update_stack_template_mock = mocker.patch.object(cluster.stack, "update_template")
    mocker.patch("common.boto3.cfn.CfnClient.update_stack_from_url")
    mock_bucket(mocker)
    mock_bucket_utils(mocker)
    mock_bucket_object_utils(mocker)

    if "Resources" not in template:
        expected_error_message = "Resources"
    elif "key" not in template.get("Resources"):
        expected_error_message = "key"
    else:
        expected_error_message = None

    if expected_error_message:
        with pytest.raises(KeyError, match=expected_error_message):
            cluster._persist_stack_resources(["key"])
        assert_that(update_stack_template_mock.called).is_false()
    else:
        cluster._persist_stack_resources(["key"])
        assert_that(update_stack_template_mock.called).is_true()
        assert_that(cluster.stack.template["Resources"]["key"]["DeletionPolicy"]).is_equal_to("Retain")


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
    cluster = dummy_cluster()

    template_property_mock = mocker.PropertyMock(return_value=template)
    mocker.patch("pcluster.models.cluster.ClusterStack.template", new_callable=template_property_mock)

    observed_return = cluster._get_unretained_cw_log_group_resource_keys()
    assert_that(observed_return).is_equal_to(expected_return)


def _mock_bucket_property(
    mocker,
    bucket_name="parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
    artifact_directory="parallelcluster/clusters/dummy-cluster-randomstring123",
):
    stack_output = {
        "Outputs": [
            {"OutputKey": "ArtifactS3RootDirectory", "OutputValue": artifact_directory},
            {"OutputKey": "ResourcesS3Bucket", "OutputValue": bucket_name},
        ]
    }
    mocker.patch("common.boto3.cfn.CfnClient.describe_stack", return_value=stack_output)
    return ClusterStack(stack_output)
