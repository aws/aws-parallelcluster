# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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


import logging

import pytest
import urllib3
import yaml
from assertpy import assert_that
from utils import StackError, generate_stack_name

from tests.custom_resource.conftest import cluster_custom_resource_provider_generator

LOGGER = logging.getLogger(__name__)


# Dynamically load pcluster library so that unit tests can pass
def pc():
    import pcluster.lib as pc

    return pc


def failure_reason(events):
    """Return the StatusReason from the most recent failed stack event."""

    def failed_event_predicate(event):
        """Predicate used to filter failed stacks to validate output."""
        failed_states = {"CREATE_FAILED", "UPDATE_FAILED"}
        return event["LogicalResourceId"] == "PclusterCluster" and event["ResourceStatus"] in failed_states

    return next(filter(failed_event_predicate, events))["ResourceStatusReason"]


def cluster_config(cluster_name):
    """Return the configuration for a cluster."""
    cluster = pc().describe_cluster(cluster_name=cluster_name)
    config_url = cluster["clusterConfiguration"]["url"]
    http = urllib3.PoolManager()
    resp = http.request(url=config_url, method="GET")
    config = yaml.safe_load(resp.data.decode("UTF-8"))
    return config


def _stack_parameter(stack, parameter_key):
    return next(filter(lambda x: x["ParameterKey"] == parameter_key, stack.parameters)).get("ParameterValue")


def test_cluster_create(region, cluster_custom_resource_factory):
    stack = cluster_custom_resource_factory()
    error_message = "KeyPairValidator"
    cluster_name = _stack_parameter(stack, "ClusterName")
    cluster = pc().list_clusters(query=f"clusters[?clusterName=='{cluster_name}']|[0]")
    assert_that(cluster["clusterStatus"]).is_not_none()
    assert_that(stack.cfn_outputs.get("ValidationMessages", "")).contains(error_message)
    assert_that(stack.cfn_outputs.get("HeadNodeIp")).is_not_none()


@pytest.mark.parametrize(
    "parameters, error_message",
    [
        ({"ClusterName": "0"}, "Bad Request: '0' does not match"),
        ({"OnNodeConfigured": "s3://invalidbucket/invalidkey"}, "OnNodeConfiguredDownloadFailure"),
    ],
)
def test_cluster_create_invalid(region, cluster_custom_resource_factory, parameters, error_message):
    """Try to create a cluster with invalid syntax and ensure that it fails."""
    with pytest.raises(StackError) as stack_error:
        cluster_custom_resource_factory(parameters)
    reason = failure_reason(stack_error.value.stack_events)
    assert_that(reason).contains(error_message)


@pytest.mark.parametrize("external_update", [(False), (True)])
# pylint: disable=too-many-locals
def test_cluster_update(region, cluster_custom_resource_factory, external_update):
    """Perform crud validation on cluster."""
    validation_message = "KeyPairValidator"
    stack = cluster_custom_resource_factory()
    cluster_name = _stack_parameter(stack, "ClusterName")
    parameters = {x["ParameterKey"]: x["ParameterValue"] for x in stack.parameters}

    old_config = cluster_config(cluster_name)
    old_max = int(old_config["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MaxCount"])
    update_parameters = {"ComputeInstanceMax": str(int(old_max) + 1)}

    # External updates are not supported due to lack of drift detection,
    # however testing here ensures we don't catastrophically fail.
    if external_update:
        config = cluster_config(cluster_name)
        max_count = update_parameters["ComputeInstanceMax"]
        config["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MaxCount"] = max_count
        cluster = pc().update_cluster(cluster_name=cluster_name, cluster_configuration=config, wait=True)

    # Update the stack
    update_params = parameters | update_parameters
    stack_params = [{"ParameterKey": k, "ParameterValue": v} for k, v in update_params.items()]
    stack.factory.update_stack(stack.name, stack.region, stack_params, stack_is_under_test=True)

    assert_that(stack.cfn_outputs["HeadNodeIp"]).is_not_none()

    # The underlying update doesn't happen if it was externally updated, so no
    # validations messages will be available in this case.
    if not external_update:
        assert_that(stack.cfn_outputs["ValidationMessages"]).contains(validation_message)

    cluster = pc().list_clusters(query=f"clusters[?clusterName=='{cluster_name}']|[0]")
    assert_that(cluster["clusterStatus"]).is_equal_to("UPDATE_COMPLETE")

    config = cluster_config(cluster_name)
    max_count = int(config["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MaxCount"])
    assert_that(max_count).is_equal_to(int(update_parameters["ComputeInstanceMax"]))


@pytest.mark.parametrize(
    "update_parameters, error_message",
    [
        ({"ClusterName": "j", "ComputeInstanceMax": "20"}, "Cannot update the ClusterName"),
        ({"ComputeInstanceMax": "10"}, "Stop the compute fleet"),
        ({"ComputeInstanceMax": "-10"}, "Must be greater than or equal to 1."),
        ({"OnNodeConfigured": "s3://invalid", "ComputeInstanceMax": "20"}, "s3 url 's3://invalid' is invalid."),
    ],
)
# pylint: disable=too-many-locals
def test_cluster_update_invalid(region, cluster_custom_resource_factory, update_parameters, error_message):
    """Perform crud validation on cluster."""
    stack = cluster_custom_resource_factory()
    cluster_name = _stack_parameter(stack, "ClusterName")
    old_cluster_status = pc().describe_cluster(cluster_name=cluster_name)
    old_config = cluster_config(cluster_name)
    parameters = {x["ParameterKey"]: x["ParameterValue"] for x in stack.parameters}

    # Update the stack to change the name
    update_params = parameters | update_parameters
    parameters = [{"ParameterKey": k, "ParameterValue": v} for k, v in update_params.items()]

    with pytest.raises(StackError) as stack_error:
        stack.factory.update_stack(stack.name, stack.region, parameters, stack_is_under_test=True)

    reason = failure_reason(stack_error.value.stack_events)
    assert_that(reason).contains(error_message)

    cluster = pc().list_clusters(query=f"clusters[?clusterName=='{cluster_name}']|[0]")
    assert_that(cluster["clusterName"]).is_equal_to(cluster_name)
    config = cluster_config(cluster_name)
    new_max = int(config["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MaxCount"])
    old_max = int(old_config["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MaxCount"])
    assert_that(new_max).is_equal_to(old_max)

    cluster_status = pc().describe_cluster(cluster_name=cluster_name)
    assert_that(old_cluster_status["lastUpdatedTime"]).is_equal_to(cluster_status["lastUpdatedTime"])


def test_cluster_delete_out_of_band(
    request, region, cfn, cluster_custom_resource_provider, cluster_custom_resource_factory
):
    """Perform crud validation on cluster."""

    stack = cluster_custom_resource_factory()
    cluster_name = _stack_parameter(stack, "ClusterName")

    # Delete the stack outside of CFN
    pc().delete_cluster(cluster_name=cluster_name)

    # Delete the stack through CFN and wait for delete to complete
    stack.factory.delete_stack(stack.name, stack.region)
    status = cfn.describe_stacks(StackName=stack.cfn_stack_id)["Stacks"][0]["StackStatus"]
    assert_that(status).is_equal_to("DELETE_COMPLETE")


def test_cluster_delete_retain(request, region, cluster_custom_resource_provider, cluster_custom_resource_factory):
    """Perform crud validation on cluster."""

    stack = cluster_custom_resource_factory({"DeletionPolicy": "Retain"})
    cluster_name = _stack_parameter(stack, "ClusterName")

    # Delete the stack through CFN and wait for delete to complete
    stack.factory.delete_stack(stack.name, stack.region)

    cluster = pc().describe_cluster(cluster_name=cluster_name)
    assert_that(cluster["clusterStatus"]).is_equal_to("CREATE_COMPLETE")
    pc().delete_cluster(cluster_name=cluster_name)


@pytest.mark.parametrize(
    "stack_param, cfn_output",
    [
        ("CustomLambdaRole", "ParallelClusterLambdaRoleArn"),
        ("AdditionalIamPolicies", "ResourceBucketAccess"),
    ],
)
def test_cluster_create_with_custom_policies(
    cfn_stacks_factory,
    request,
    region,
    resource_bucket,
    resource_bucket_policies,
    cluster_custom_resource_provider_template,
    cluster_custom_resource_factory,
    stack_param,
    cfn_output,
):
    """Create a custom resource provider with a custom role and create a cluster to validate it."""
    parameters = {"CustomBucket": resource_bucket, stack_param: resource_bucket_policies.cfn_outputs[cfn_output]}
    custom_resource_gen = cluster_custom_resource_provider_generator(
        cfn_stacks_factory,
        region,
        generate_stack_name("custom-resource-provider", request.config.getoption("stackname_suffix")),
        parameters,
        cluster_custom_resource_provider_template,
    )
    service_token = next(custom_resource_gen)

    cluster_parameters = {"CustomBucketAccess": resource_bucket, "ServiceToken": service_token}
    stack = cluster_custom_resource_factory(cluster_parameters)
    cluster_name = _stack_parameter(stack, "ClusterName")
    cluster = pc().list_clusters(query=f"clusters[?clusterName=='{cluster_name}']|[0]")
    assert_that(cluster["clusterStatus"]).is_equal_to("CREATE_COMPLETE")
