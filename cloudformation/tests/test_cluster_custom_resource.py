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


# The following functions late-bind the library as it is only used locally
def _list_clusters(cluster_name):
    """List clusters and filter by name."""
    import pcluster.lib as pcluster

    return pcluster.list_clusters(query=f"clusters[?clusterName=='{cluster_name}']|[0]")


def _describe_cluster(cluster_name):
    """Late bind library and describe cluster."""
    import pcluster.lib as pcluster

    return pcluster.describe_cluster(cluster_name=cluster_name)


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
        "ServiceToken": cluster_custom_resource["Function"],
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


@pytest.mark.parametrize(
    "parameters",
    [
        ({"ClusterName": "0"}),
        ({"OnNodeConfigured": "s3://invalidbucket/invlidkey"}),
    ],
)
@pytest.mark.local
def test_cluster_create_invalid_syntax(cfn, default_vpc, cluster_custom_resource, parameters):
    """Try to create a cluster with invalid syntax and ensure that it fails."""
    stack_name = random.choice(string.ascii_lowercase) + random_str()
    cluster_name = f"c-{stack_name}"
    parameters = {
        "ClusterName": cluster_name,
        "HeadNodeSubnet": default_vpc["PublicSubnetId"],
        "ComputeNodeSubnet": default_vpc["PrivateSubnetId"],
        "ServiceToken": cluster_custom_resource["Function"],
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

    # Stack will be in a ROLLBACK_COMPLETE state at this point, so delete it
    cfn.delete_stack(StackName=stack_name)
    cfn.get_waiter("stack_delete_complete").wait(StackName=stack_name)


@pytest.mark.local
def test_cluster_update(cfn, cluster):
    """Perform crud validation on cluster."""
    stack_name, cluster_name, parameters = cluster

    # Update the stack
    update_params = {"ComputeInstanceMax": "8", **parameters}
    cfn.update_stack(
        StackName=stack_name,
        UsePreviousTemplate=True,
        Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in update_params.items()],
    )
    cfn.get_waiter("stack_update_complete").wait(StackName=stack_name)

    cluster = _list_clusters(cluster_name)
    assert_that(cluster["clusterStatus"]).is_equal_to("UPDATE_COMPLETE")
    config = cluster_config(cluster_name)
    assert_that(int(config["Scheduling"]["SlurmQueues"][0]["ComputeResources"][0]["MaxCount"])).is_equal_to(8)


@pytest.mark.parametrize(
    "update_parameters",
    [
        ({"ClusterName": "j"}),
        ({"ComputeInstanceMax": "-10"}),
        ({"OnNodeConfigured": "s3://invalidpath"}),
    ],
)
@pytest.mark.local
def test_update_invalid(cfn, cluster, update_parameters):
    """Perform crud validation on cluster."""
    stack_name, cluster_name, parameters = cluster

    old_cluster_status = _describe_cluster(cluster_name)
    old_config = cluster_config(cluster_name)

    # Update the stack to change the name
    update_params = {**parameters, **update_parameters}
    cfn.update_stack(
        StackName=stack_name,
        UsePreviousTemplate=True,
        Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in update_params.items()],
    )
    with pytest.raises(botocore.exceptions.WaiterError):
        cfn.get_waiter("stack_update_complete").wait(StackName=stack_name)

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
        "ServiceToken": cluster_custom_resource["Function"],
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
