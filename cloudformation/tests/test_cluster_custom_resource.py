"""Test cases for Cluster CloudFormation Custom Resource."""
import random
import string

import botocore
import pytest
import urllib3
import yaml
from assertpy import assert_that
from conftest import cfn_stack_generator, random_str

CLUSTER_TEMPLATE = "../custom_resource/cluster.yaml"
TEST_CLUSTER = "test_cluster.yaml"


def failure_reason(cfn, stack_name):
    """Return the StatusReason from the most recent failed stack event."""

    def failed_event_predicate(event):
        """Predicate used to filter failed stacks to validate output."""
        failed_states = {"CREATE_FAILED", "UPDATE_FAILED"}
        return event["LogicalResourceId"] == "PclusterCluster" and event["ResourceStatus"] in failed_states

    events = cfn.describe_stack_events(StackName=stack_name)["StackEvents"]
    return next(filter(failed_event_predicate, events))["ResourceStatusReason"]


# The following functions late-bind the library as it is only used locally
def _list_clusters(cluster_name):
    """List clusters and filter by name."""
    import pcluster.lib as pcluster

    return pcluster.list_clusters(query=f"clusters[?clusterName=='{cluster_name}']|[0]")


def _describe_cluster(cluster_name):
    """Late bind library and describe cluster."""
    import pcluster.lib as pcluster

    return pcluster.describe_cluster(cluster_name=cluster_name)


def _update_cluster(cluster_name, config, **kwargs):
    """Late bind library and describe cluster."""
    import pcluster.lib as pcluster

    return pcluster.update_cluster(cluster_name=cluster_name, cluster_configuration=config, **kwargs)


def _delete_cluster(cluster_name):
    """Late bind library and delete cluster."""
    import pcluster.lib as pcluster

    return pcluster.delete_cluster(cluster_name=cluster_name)


def cluster_config(cluster_name):
    """Return the configuration for a cluster."""
    cluster = _describe_cluster(cluster_name)
    config_url = cluster["clusterConfiguration"]["url"]
    http = urllib3.PoolManager()
    resp = http.request(url=config_url, method="GET")
    config = yaml.safe_load(resp.data.decode("UTF-8"))
    return config


@pytest.fixture(scope="module", name="cluster_custom_resource")
def cluster_custom_resource_fixture():
    """Create the cluster custom resource stack."""
    capabilities = ["CAPABILITY_IAM", "CAPABILITY_AUTO_EXPAND"]
    yield from cfn_stack_generator(CLUSTER_TEMPLATE, random_str(), None, capabilities)


@pytest.fixture(scope="module", name="cluster")
def cluster_fixture(cfn, default_vpc, cluster_custom_resource):
    """Create a basic cluster through CFN, wait for it to start and return it."""
    stack_name = random.choice(string.ascii_lowercase) + random_str()
    cluster_name = f"c-{stack_name}"
    parameters = {
        "ClusterName": cluster_name,
        "HeadNodeSubnet": default_vpc["PublicSubnetId"],
        "ComputeNodeSubnet": default_vpc["PrivateSubnetId"],
        "ServiceToken": cluster_custom_resource["ServiceToken"],
    }

    with open(TEST_CLUSTER, encoding="utf-8") as templ:
        template = templ.read()

    # Create the cluster using CloudFormation directly
    cfn.create_stack(
        StackName=stack_name,
        TemplateBody=template,
        Capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
        Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in parameters.items()],
    )

    # Wait for it to create
    cfn.get_waiter("stack_create_complete").wait(StackName=stack_name)

    # Validate that CFN sees the stack creation as "CREATE_COMPLETE"
    stack = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]
    status = stack["StackStatus"]
    stack_id = stack["StackId"]
    assert_that(status).is_equal_to("CREATE_COMPLETE")

    # Validate that PC sees the cluster as "CREATE_COMPLETE"
    cluster = _list_clusters(cluster_name)
    assert_that(cluster["clusterStatus"]).is_equal_to("CREATE_COMPLETE")

    try:
        yield stack_name, cluster_name, parameters

        # Delete the stack through CFN and wait for delete to complete
        cfn.delete_stack(StackName=stack_name)
        cfn.get_waiter("stack_delete_complete").wait(StackName=stack_name)
        status = cfn.describe_stacks(StackName=stack_id)["Stacks"][0]["StackStatus"]
        assert_that(status).is_equal_to("DELETE_COMPLETE")

        # Validate that PC sees the cluster as deleted
        cluster = _list_clusters(cluster_name)
        assert_that(cluster).is_none()
    except Exception as exc:
        cfn.delete_stack(StackName=stack_id)
        raise exc


@pytest.mark.local
def test_cluster_create(cfn, cluster):
    """Use the fixture to validate creation ."""
    stack_name, cluster_name, _parameters = cluster
    error_message = "KeyPairValidator"
    stack = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]
    assert_that(stack["StackStatus"]).is_not_none()

    # Validate that PC sees the cluster, state might but updated depending on test order
    cluster = _list_clusters(cluster_name)
    assert_that(cluster["clusterStatus"]).is_not_none()

    outputs = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["Outputs"]
    head_node_ip = next(filter(lambda x: x["OutputKey"] == "HeadNodeIp", outputs)).get("OutputValue")
    validation_messages = next(filter(lambda x: x["OutputKey"] == "ValidationMessages", outputs)).get("OutputValue")
    assert_that(validation_messages).contains(error_message)
    assert_that(head_node_ip).is_not_none()


@pytest.mark.parametrize(
    "parameters, error_message",
    [
        ({"ClusterName": "0"}, "Bad Request: '0' does not match"),
        ({"OnNodeConfigured": "s3://invalidbucket/invlidkey"}, "OnNodeConfiguredDownloadFailure"),
    ],
)
@pytest.mark.local
def test_cluster_create_invalid(cfn, default_vpc, cluster_custom_resource, parameters, error_message):
    """Try to create a cluster with invalid syntax and ensure that it fails."""
    stack_name = random.choice(string.ascii_lowercase) + random_str()
    cluster_name = f"c-{stack_name}"
    parameters = {
        "ClusterName": cluster_name,
        "HeadNodeSubnet": default_vpc["PublicSubnetId"],
        "ComputeNodeSubnet": default_vpc["PrivateSubnetId"],
        "ServiceToken": cluster_custom_resource["ServiceToken"],
        **parameters,
    }

    with open(TEST_CLUSTER, encoding="utf-8") as templ:
        template = templ.read()

    # Create the cluster using CloudFormation directly
    cfn.create_stack(
        StackName=stack_name,
        TemplateBody=template,
        Capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
        Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in parameters.items()],
    )

    with pytest.raises(botocore.exceptions.WaiterError):
        cfn.get_waiter("stack_create_complete").wait(StackName=stack_name)

    reason = failure_reason(cfn, stack_name)
    assert_that(reason).contains(error_message)

    # Stack will be in a ROLLBACK_COMPLETE state at this point, so delete it
    cfn.delete_stack(StackName=stack_name)
    cfn.get_waiter("stack_delete_complete").wait(StackName=stack_name)


@pytest.mark.parametrize(
    "external_update",
    [
        (False),
        (True),
    ],
)
@pytest.mark.local
# pylint: disable=too-many-locals
def test_cluster_update(cfn, cluster, external_update):
    """Perform crud validation on cluster."""
    stack_name, cluster_name, parameters = cluster
    validation_message = "KeyPairValidator"

    old_config = cluster_config(cluster_name)
    old_max = int(old_config["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MaxCount"])
    update_parameters = {"ComputeInstanceMax": str(int(old_max) + 1)}

    # External updates are not supported due to lack of drift detection,
    # however testing here ensures we don't catastrophically fail.
    if external_update:
        config = cluster_config(cluster_name)
        max_count = update_parameters["ComputeInstanceMax"]
        config["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MaxCount"] = max_count
        cluster = _update_cluster(cluster_name, config, wait=True)

    # Update the stack
    update_params = parameters | update_parameters
    cfn.update_stack(
        StackName=stack_name,
        UsePreviousTemplate=True,
        Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in update_params.items()],
    )
    cfn.get_waiter("stack_update_complete").wait(StackName=stack_name)

    outputs = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["Outputs"]
    head_node_ip = next(filter(lambda x: x["OutputKey"] == "HeadNodeIp", outputs)).get("OutputValue")
    assert_that(head_node_ip).is_not_none()

    # The underlying update doesn't happen if it was externally updated, so no
    # validations messages will be available in this case.
    if not external_update:
        validation_messages = next(filter(lambda x: x["OutputKey"] == "ValidationMessages", outputs)).get("OutputValue")
        assert_that(validation_messages).contains(validation_message)

    cluster = _list_clusters(cluster_name)
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
@pytest.mark.local
# pylint: disable=too-many-locals
def test_cluster_update_invalid(cfn, cluster, update_parameters, error_message):
    """Perform crud validation on cluster."""
    stack_name, cluster_name, parameters = cluster

    old_cluster_status = _describe_cluster(cluster_name)
    old_config = cluster_config(cluster_name)

    # Update the stack to change the name
    update_params = parameters | update_parameters
    cfn.update_stack(
        StackName=stack_name,
        UsePreviousTemplate=True,
        Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in update_params.items()],
    )
    with pytest.raises(botocore.exceptions.WaiterError):
        cfn.get_waiter("stack_update_complete").wait(StackName=stack_name)

    assert_that(failure_reason(cfn, stack_name)).contains(error_message)

    cluster = _list_clusters(cluster_name)
    assert_that(cluster["clusterName"]).is_equal_to(cluster_name)
    config = cluster_config(cluster_name)
    new_max = int(config["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MaxCount"])
    old_max = int(old_config["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MaxCount"])
    assert_that(new_max).is_equal_to(old_max)

    cluster_status = _describe_cluster(cluster_name)
    assert_that(old_cluster_status["lastUpdatedTime"]).is_equal_to(cluster_status["lastUpdatedTime"])


@pytest.mark.local
def test_cluster_delete_out_of_band(cfn, default_vpc, cluster_custom_resource):
    """Perform crud validation on cluster."""
    stack_name = random.choice(string.ascii_lowercase) + random_str()
    cluster_name = f"c-{stack_name}"
    parameters = {
        "ClusterName": cluster_name,
        "HeadNodeSubnet": default_vpc["PublicSubnetId"],
        "ComputeNodeSubnet": default_vpc["PrivateSubnetId"],
        "ServiceToken": cluster_custom_resource["ServiceToken"],
    }

    with open(TEST_CLUSTER, encoding="utf-8") as templ:
        template = templ.read()

    # Create the cluster using CloudFormation directly
    cfn.create_stack(
        StackName=stack_name,
        TemplateBody=template,
        Capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
        Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in parameters.items()],
    )

    stack = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]
    stack_id = stack["StackId"]

    # Wait for it to create
    cfn.get_waiter("stack_create_complete").wait(StackName=stack_name)

    _delete_cluster(cluster_name)

    # Delete the stack through CFN and wait for delete to complete
    cfn.delete_stack(StackName=stack_name)
    cfn.get_waiter("stack_delete_complete").wait(StackName=stack_name)
    status = cfn.describe_stacks(StackName=stack_id)["Stacks"][0]["StackStatus"]
    assert_that(status).is_equal_to("DELETE_COMPLETE")
