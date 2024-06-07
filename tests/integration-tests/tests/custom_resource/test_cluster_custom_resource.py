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

import boto3
import pytest
import urllib3
import yaml
from assertpy import assert_that
from utils import StackError, generate_stack_name

from tests.custom_resource.conftest import cluster_custom_resource_provider_generator, get_custom_resource_template

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


def _get_parameter_if_available(key_attribute_name, key, collection, value_attribute_name):
    filtered_collection = filter(lambda x: x[key_attribute_name] == key, collection)
    try:
        return next(filtered_collection).get(value_attribute_name, None)
    except StopIteration:
        return None


def _stack_parameter(stack, parameter_key):
    return _get_parameter_if_available("ParameterKey", parameter_key, stack.parameters, "ParameterValue")


def _cluster_tag(cluster, tag_key):
    return _get_parameter_if_available("key", tag_key, cluster["tags"], "value")


def _stack_tag(stack, tag_key):
    return _get_parameter_if_available("Key", tag_key, stack.tags, "Value")


@pytest.mark.usefixtures("instance", "os", "region")
def test_cluster_create(cluster_custom_resource_factory, pcluster_config_reader):
    error_message = "KeyPairValidator"
    cluster_config_path = pcluster_config_reader(no_of_queues=50)
    stack = cluster_custom_resource_factory(cluster_config_path)
    cluster_name = _stack_parameter(stack, "ClusterName")
    cluster = pc().describe_cluster(cluster_name=cluster_name)
    assert_that(cluster["clusterStatus"]).is_not_none()
    assert_that(_cluster_tag(cluster, "cluster_name")).is_equal_to(cluster_name)
    assert_that(_cluster_tag(cluster, "inside_configuration_key")).is_equal_to("overridden")
    assert_that(_cluster_tag(cluster, "parallelcluster:custom_resource")).is_equal_to("cluster")
    assert_that(stack.cfn_outputs.get("ValidationMessages", "")).contains(error_message)
    assert_that(stack.cfn_outputs.get("HeadNodeIp")).is_not_none()


@pytest.mark.usefixtures("instance", "os", "region")
def test_cluster_create_invalid(cluster_custom_resource_factory, pcluster_config_reader):
    """Try to create a cluster with invalid syntax and ensure that it fails."""
    cluster_config_path = pcluster_config_reader()

    with pytest.raises(StackError) as stack_error:
        cluster_custom_resource_factory(cluster_config_path, cluster_name="0")
    reason = failure_reason(stack_error.value.stack_events)
    assert_that(reason).contains("Bad Request: '0' does not match")

    with pytest.raises(StackError) as stack_error:
        cluster_custom_resource_factory(cluster_config_path)
    reason = failure_reason(stack_error.value.stack_events)
    assert_that(reason).contains("OnNodeConfiguredDownloadFailure")


@pytest.mark.usefixtures("instance", "os", "region")
@pytest.mark.parametrize("external_update", [False, True])
# pylint: disable=too-many-locals
def test_cluster_update(cluster_custom_resource_factory, external_update, pcluster_config_reader):
    """Test update basic behaviours."""
    validation_message = "KeyPairValidator"
    max_count = 3
    cluster_config_path = pcluster_config_reader(no_of_queues=50, max_count=max_count)
    stack = cluster_custom_resource_factory(cluster_config_path)
    cluster_name = _stack_parameter(stack, "ClusterName")

    new_max = max_count + 1

    # External updates are not supported due to lack of drift detection,
    # however testing here ensures we don't catastrophically fail.
    if external_update:
        config = cluster_config(cluster_name)
        config["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MaxCount"] = new_max
        pc().update_cluster(cluster_name=cluster_name, cluster_configuration=config, wait=True)

    # Update the stack
    template_body = boto3.client("cloudformation").get_template(StackName=stack.name)["TemplateBody"]
    template_body = template_body.replace(f"MaxCount: {max_count}", f"MaxCount: {new_max}")
    stack.factory.update_stack(
        stack.name, stack.region, stack.parameters, template_body=template_body, stack_is_under_test=True
    )

    assert_that(stack.cfn_outputs["HeadNodeIp"]).is_not_none()

    # The underlying update doesn't happen if it was externally updated, so no
    # validations messages will be available in this case.
    if not external_update:
        assert_that(stack.cfn_outputs["ValidationMessages"]).contains(validation_message)

    cluster = pc().list_clusters(query=f"clusters[?clusterName=='{cluster_name}']|[0]")
    assert_that(cluster["clusterStatus"]).is_equal_to("UPDATE_COMPLETE")

    config = cluster_config(cluster_name)
    max_count = int(config["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MaxCount"])
    assert_that(max_count).is_equal_to(new_max)


@pytest.mark.usefixtures("instance", "os", "region")
# pylint: disable=too-many-locals
def test_cluster_update_invalid(
    cluster_custom_resource_factory, pcluster_config_reader, cluster_custom_resource_template
):
    """Try to update cluster with invalid values, assert validators errors and ensure the cluster is not updated."""
    stack = cluster_custom_resource_factory(pcluster_config_reader())
    cluster_name = _stack_parameter(stack, "ClusterName")
    old_cluster_status = pc().describe_cluster(cluster_name=cluster_name)
    old_config = cluster_config(cluster_name)
    parameters = {x["ParameterKey"]: x["ParameterValue"] for x in stack.parameters}

    # Update the stack to change the name
    update_params = parameters | {"ClusterName": "j"}
    change_cluster_name_parameters = [{"ParameterKey": k, "ParameterValue": v} for k, v in update_params.items()]

    with pytest.raises(StackError) as stack_error:
        stack.factory.update_stack(
            stack.name, stack.region, change_cluster_name_parameters, stack_is_under_test=True, wait_for_rollback=True
        )

    reason = failure_reason(stack_error.value.stack_events)
    assert_that(reason).contains("Cannot update the ClusterName")

    for cluster_config_path, error, suppress_validators in [
        # CloudFormation truncates error messages,
        # so we cannot specify the full error message here, but only a part of it.
        ("pcluster.config.reducemaxcount.yaml", "Stop the compute fleet or set QueueUpdateStrategy:TERMINATE", None),
        ("pcluster.config.negativemaxcount.yaml", "Must be greater than or equal to 1.", None),
        ("pcluster.config.invalidprofile.yaml", "cannot be found", ["type:InstanceProfileValidator"]),
        ("pcluster.config.wrongscripturi.yaml", "s3 url 's3://invalid' is invalid.", None),
    ]:
        template = get_custom_resource_template(
            cluster_config_path=pcluster_config_reader(cluster_config_path),
            cluster_custom_resource_template=cluster_custom_resource_template,
            suppress_validators=suppress_validators,
        )
        with pytest.raises(StackError) as stack_error:
            stack.factory.update_stack(
                stack.name,
                stack.region,
                stack.parameters,
                template_body=template.to_yaml(),
                stack_is_under_test=True,
                wait_for_rollback=True,
            )
        if suppress_validators:
            assert_that(stack.cfn_outputs.get("ValidationMessages", "")).does_not_contain(error)
        else:
            reason = failure_reason(stack_error.value.stack_events)
            assert_that(reason).contains(error)

    cluster = pc().list_clusters(query=f"clusters[?clusterName=='{cluster_name}']|[0]")
    assert_that(cluster["clusterName"]).is_equal_to(cluster_name)
    config = cluster_config(cluster_name)
    new_max = int(config["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MaxCount"])
    old_max = int(old_config["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MaxCount"])
    assert_that(new_max).is_equal_to(old_max)

    cluster_status = pc().describe_cluster(cluster_name=cluster_name)
    assert_that(old_cluster_status["lastUpdatedTime"]).is_equal_to(cluster_status["lastUpdatedTime"])


@pytest.mark.usefixtures("instance", "os", "region")
@pytest.mark.parametrize("config_parameter_change", [False, True])
def test_cluster_update_tag_propagation(
    cluster_custom_resource_factory, config_parameter_change, pcluster_config_reader
):
    """Verify tags are properly updated ."""
    max_count = 16
    cluster_config = pcluster_config_reader(max_count=max_count)
    stack = cluster_custom_resource_factory(cluster_config)
    cluster_name = _stack_parameter(stack, "ClusterName")

    stack_tags = [
        {"Key": "cluster_name", "Value": "new_cluster_name"},
        {"Key": "inside_configuration_key", "Value": "stack_level_value"},
        {"Key": "new_key", "Value": "new_value"},
    ]

    if config_parameter_change:
        new_max = max_count + 1
        template_body = boto3.client("cloudformation").get_template(StackName=stack.name)["TemplateBody"]
        template_body = template_body.replace(f"MaxCount: {max_count}", f"MaxCount: {new_max}")

        # Update the stack
        with pytest.raises(StackError) as stack_error:
            stack.factory.update_stack(
                stack.name,
                stack.region,
                stack.parameters,
                stack_is_under_test=True,
                tags=stack_tags,
                wait_for_rollback=True,
                template_body=template_body,
            )
        reason = failure_reason(stack_error.value.stack_events)
        assert_that(reason).contains(
            "If you need this change, please consider creating a new cluster instead of updating the existing one"
        )
        # Root stack tags here do not update because the stack gets rolled back after cluster update failure
        assert_that(_stack_tag(stack, "cluster_name")).is_equal_to(cluster_name)
        assert_that(_stack_tag(stack, "inside_configuration_key")).is_equal_to("stack_level_value")
        assert_that(_stack_tag(stack, "new_key")).is_none()
    else:
        stack.factory.update_stack(
            stack.name, stack.region, stack.parameters, stack_is_under_test=True, tags=stack_tags
        )
        # Root stack tags here do update because the cluster update is not triggered,
        # so it does not fail, and the update is not rolled back
        assert_that(_stack_tag(stack, "cluster_name")).is_equal_to("new_cluster_name")
        assert_that(_stack_tag(stack, "inside_configuration_key")).is_equal_to("stack_level_value")
        assert_that(_stack_tag(stack, "new_key")).is_equal_to("new_value")

    assert_that(stack.cfn_outputs["HeadNodeIp"]).is_not_none()

    cluster = pc().describe_cluster(cluster_name=cluster_name)

    # Cluster Tags are never supposed to change, because
    # 1. If the config is changed update validation will fail as tags update is unsupported in ParallelCluster
    # 2. If the config is unchanged no update on the cluster stack is triggered
    # So the state of the cluster is never supposed to change when tags are updated
    assert_that(_cluster_tag(cluster, "cluster_name")).is_equal_to(cluster_name)
    assert_that(_cluster_tag(cluster, "inside_configuration_key")).is_equal_to("overridden")
    assert_that(_cluster_tag(cluster, "new_key")).is_none()
    assert_that(cluster["clusterStatus"]).is_equal_to("CREATE_COMPLETE")


@pytest.mark.usefixtures("instance", "os", "region")
def test_cluster_delete_out_of_band(cfn, cluster_custom_resource_factory, pcluster_config_reader):
    """Perform crud validation on cluster."""

    stack = cluster_custom_resource_factory(pcluster_config_reader())
    cluster_name = _stack_parameter(stack, "ClusterName")

    # Delete the stack outside of CFN
    pc().delete_cluster(cluster_name=cluster_name)

    # Delete the stack through CFN and wait for delete to complete
    stack.factory.delete_stack(stack.name, stack.region)
    status = cfn.describe_stacks(StackName=stack.cfn_stack_id)["Stacks"][0]["StackStatus"]
    assert_that(status).is_equal_to("DELETE_COMPLETE")


@pytest.mark.usefixtures("instance", "os", "region")
def test_cluster_delete_retain(cluster_custom_resource_factory, pcluster_config_reader):
    """Perform crud validation on cluster."""

    stack = cluster_custom_resource_factory(pcluster_config_reader(), deletion_policy="Retain")
    cluster_name = _stack_parameter(stack, "ClusterName")

    # Delete the stack through CFN and wait for delete to complete
    stack.factory.delete_stack(stack.name, stack.region)

    cluster = pc().describe_cluster(cluster_name=cluster_name)
    assert_that(cluster["clusterStatus"]).is_equal_to("CREATE_COMPLETE")
    pc().delete_cluster(cluster_name=cluster_name)


@pytest.mark.usefixtures("instance", "os")
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
    pcluster_config_reader,
):
    """Create a custom resource provider with a custom role and create a cluster to validate it."""
    parameters = {"CustomBucket": resource_bucket, stack_param: resource_bucket_policies.cfn_outputs[cfn_output]}
    provider_stack_name = generate_stack_name(
        "integ-test-custom-resource-provider", request.config.getoption("stackname_suffix")
    )
    custom_resource_gen = cluster_custom_resource_provider_generator(
        cfn_stacks_factory,
        region,
        provider_stack_name,
        parameters,
        cluster_custom_resource_provider_template,
    )
    service_token = next(custom_resource_gen)

    if stack_param == "CustomLambdaRole":
        logging.info("Checking no IAM resources are created when CustomLambdaRole is specified")
        resources = boto3.client("cloudformation").describe_stack_resources(StackName=provider_stack_name)[
            "StackResources"
        ]
        for resource in resources:
            resource_type = resource["ResourceType"]
            assert_that(resource_type).does_not_contain("AWS::IAM::")

    stack = cluster_custom_resource_factory(pcluster_config_reader(), service_token=service_token)
    cluster_name = _stack_parameter(stack, "ClusterName")
    cluster = pc().list_clusters(query=f"clusters[?clusterName=='{cluster_name}']|[0]")
    assert_that(cluster["clusterStatus"]).is_equal_to("CREATE_COMPLETE")


def test_cluster_1_click(cluster_1_click):
    """Create a cluster using the 1-click template to validate it."""
    head_node_ip = cluster_1_click.cfn_outputs.get("HeadNodeIp")
    system_manager_url = cluster_1_click.cfn_outputs.get("SystemManagerUrl")
    assert_that(head_node_ip).is_not_empty()
    assert_that(system_manager_url).is_not_empty()
