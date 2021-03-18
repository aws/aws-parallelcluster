# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from typing import List

import pytest
from assertpy import assert_that

from common.aws.aws_resources import InstanceInfo
from pcluster.constants import PCLUSTER_NAME_MAX_LENGTH
from pcluster.models.cluster import ClusterActionError, NodeType
from pcluster.models.cluster_config import Resource, Tag
from pcluster.validators.common import FailureLevel, Validator
from tests.common.dummy_aws_api import DummyAWSApi
from tests.pcluster.models.cluster_dummy_model import dummy_slurm_cluster_config
from tests.pcluster.test_utils import dummy_cluster


class FakeInfoValidator(Validator):
    """Dummy validator of info level."""

    def _validate(self, param):
        self._add_failure(f"Wrong value {param}.", FailureLevel.INFO)


class FakeErrorValidator(Validator):
    """Dummy validator of error level."""

    def _validate(self, param):
        self._add_failure(f"Error {param}.", FailureLevel.ERROR)


class FakeComplexValidator(Validator):
    """Dummy validator requiring multiple parameters as input."""

    def _validate(self, fake_attribute, other_attribute):
        self._add_failure(f"Combination {fake_attribute} - {other_attribute}.", FailureLevel.WARNING)


class FakePropertyValidator(Validator):
    """Dummy property validator of info level."""

    def _validate(self, property_value: str):
        self._add_failure(f"Wrong value {property_value}.", FailureLevel.INFO)


def _assert_validation_result(result, expected_level, expected_message):
    """Assert that validation results is the expected one, by checking level and message."""
    assert_that(result.level).is_equal_to(expected_level)
    assert_that(result.message).contains(expected_message)


def test_resource_validate():
    """Verify that validators are executed in the right order according to priorities with the expected params."""

    class FakeResource(Resource):
        """Fake resource class to test validators."""

        def __init__(self):
            super().__init__()
            self.fake_attribute = "fake-value"
            self.other_attribute = "other-value"

        def _validate(self):
            self._execute_validator(FakeErrorValidator, param=self.fake_attribute)
            self._execute_validator(
                FakeComplexValidator,
                fake_attribute=self.fake_attribute,
                other_attribute=self.other_attribute,
            )
            self._execute_validator(FakeInfoValidator, param=self.other_attribute)

    fake_resource = FakeResource()
    validation_failures = fake_resource.validate()

    # Verify high prio is the first of the list
    _assert_validation_result(validation_failures[0], FailureLevel.ERROR, "Error fake-value.")
    _assert_validation_result(validation_failures[1], FailureLevel.WARNING, "Combination fake-value - other-value.")
    _assert_validation_result(validation_failures[2], FailureLevel.INFO, "Wrong value other-value.")


def test_dynamic_property_validate():
    """Verify that validators of dynamic parameters are working as expected."""

    class FakeResource(Resource):
        """Fake resource class to test validators."""

        def __init__(self):
            super().__init__()
            self.deps_value = ""

        def _validate(self):
            self._execute_validator(FakePropertyValidator, property_value=self.dynamic_attribute)

        @property
        def dynamic_attribute(self):
            return f"dynamic-value: {self.deps_value}"

    fake_resource = FakeResource()
    validation_failures = fake_resource.validate()
    _assert_validation_result(
        validation_failures[0], FailureLevel.INFO, f"Wrong value dynamic-value: {fake_resource.deps_value}."
    )

    fake_resource.deps_value = "test1"
    validation_failures = fake_resource.validate()
    _assert_validation_result(
        validation_failures[0], FailureLevel.INFO, f"Wrong value dynamic-value: {fake_resource.deps_value}."
    )

    fake_resource.deps_value = "test2"
    validation_failures = fake_resource.validate()
    _assert_validation_result(
        validation_failures[0], FailureLevel.INFO, f"Wrong value dynamic-value: {fake_resource.deps_value}."
    )


def test_nested_resource_validate():
    """Verify that validators of nested resources are executed correctly."""

    class FakeNestedResource(Resource):
        """Fake nested resource class to test validators."""

        def __init__(self, fake_value):
            super().__init__()
            self.fake_attribute = fake_value

        def _validate(self):
            self._execute_validator(FakeErrorValidator, param=self.fake_attribute)

    class FakeParentResource(Resource):
        """Fake resource class to test validators."""

        def __init__(self, nested_resource: FakeNestedResource, list_of_resources: List[FakeNestedResource]):
            super().__init__()
            self.fake_resource = nested_resource
            self.other_attribute = "other-value"
            self.list_of_resources = list_of_resources

        def _validate(self):
            self._execute_validator(FakeInfoValidator, param=self.other_attribute)

    fake_resource = FakeParentResource(FakeNestedResource("value1"), [FakeNestedResource("value2")])
    validation_failures = fake_resource.validate()

    # Verify children failures are executed first
    _assert_validation_result(validation_failures[0], FailureLevel.ERROR, "Error value1.")
    _assert_validation_result(validation_failures[1], FailureLevel.ERROR, "Error value2.")
    _assert_validation_result(validation_failures[2], FailureLevel.INFO, "Wrong value other-value.")


@pytest.mark.parametrize(
    "node_type, expected_response, expected_instances",
    [
        (NodeType.HEAD_NODE, [{}], 1),
        (NodeType.COMPUTE, [{}, {}, {}], 3),
        (NodeType.COMPUTE, [{}, {}], 2),
        (NodeType.COMPUTE, [], 0),
    ],
)
def test_describe_instances(mocker, node_type, expected_response, expected_instances):
    instance_state_list = ["pending", "running", "stopping", "stopped"]
    mocker.patch("common.aws.aws_api.AWSApi.instance", return_value=DummyAWSApi())
    mocker.patch(
        "common.boto3.ec2.Ec2Client.describe_instances",
        return_value=[InstanceInfo(instance) for instance in expected_response],
        expected_params=[
            {"Name": "tag:Application", "Values": ["test-cluster"]},
            {"Name": "instance-state-name", "Values": instance_state_list},
            {"Name": "tag:aws-parallelcluster-node-type", "Values": [str(node_type)]},
        ],
    )

    cluster = dummy_cluster()
    instances = cluster._describe_instances(node_type=node_type)

    assert_that(instances).is_length(expected_instances)


@pytest.mark.parametrize(
    "head_node_instance, expected_ip, error",
    [
        (
            {
                "PrivateIpAddress": "10.0.16.17",
                "PublicIpAddress": "18.188.93.193",
                "State": {"Code": 16, "Name": "running"},
            },
            "18.188.93.193",
            None,
        ),
        ({"PrivateIpAddress": "10.0.16.17", "State": {"Code": 16, "Name": "running"}}, "10.0.16.17", None),
        (
            {
                "PrivateIpAddress": "10.0.16.17",
                "PublicIpAddress": "18.188.93.193",
                "State": {"Code": 16, "Name": "stopped"},
            },
            "18.188.93.193",
            "Head node: STOPPED",
        ),
    ],
    ids=["public_ip", "private_ip", "stopped"],
)
def test_get_head_node_ips(mocker, head_node_instance, expected_ip, error):
    cluster = dummy_cluster()
    mocker.patch.object(cluster.stack, "updated_status")
    describe_cluster_instances_mock = mocker.patch.object(
        cluster, "_describe_instances", return_value=[InstanceInfo(head_node_instance)]
    )

    if error:
        with pytest.raises(ClusterActionError, match=error):
            _ = cluster.head_node_ip
    else:
        assert_that(cluster.head_node_ip).is_equal_to(expected_ip)
        describe_cluster_instances_mock.assert_called_with(node_type=NodeType.HEAD_NODE)


@pytest.mark.parametrize("existing_tags", [({}), ({"test": "testvalue"}), ({"Version": "OldVersionToBeOverridden"})])
def test_tags(mocker, existing_tags):
    """Verify that the function to get the tags list behaves as expected."""
    mocker.patch("pcluster.models.cluster_config.Efa.init_default_efa_enabled")
    cluster = dummy_cluster()
    cluster.config = dummy_slurm_cluster_config(mocker)

    # Populate config with list of existing tags
    existing_tags_list = [Tag(key=tag_name, value=tag_value) for tag_name, tag_value in existing_tags.items()]
    cluster.config.tags = existing_tags_list

    # Expected tags:
    installed_version = "FakeInstalledVersion"
    tags = {"Version": installed_version}
    tags.update(existing_tags)
    expected_tags_list = _sort_tags([Tag(key=tag_name, value=tag_value) for tag_name, tag_value in tags.items()])
    expected_cfn_tags = _sort_cfn_tags([{"Key": tag_name, "Value": tag_value} for tag_name, tag_value in tags.items()])

    # Test method to add version tag
    get_version_patch = mocker.patch("pcluster.models.cluster.get_installed_version", return_value=installed_version)
    cluster._add_version_tag()
    assert_that(get_version_patch.call_count).is_equal_to(1)
    assert_that(
        all(
            [
                source.value == target.value
                for source, target in zip(_sort_tags(cluster.config.tags), expected_tags_list)
            ]
        )
    ).is_true()

    # Test method to retrieve CFN tags
    cfn_tags = _sort_cfn_tags(cluster._get_cfn_tags())
    assert_that(
        all([source["Value"] == target["Value"] for source, target in zip(cfn_tags, expected_cfn_tags)])
    ).is_true()


def _sort_tags(tags):
    return sorted(tags, key=lambda tag: tag.key)


def _sort_cfn_tags(tags):
    return sorted(tags, key=lambda tag: tag["Key"])


@pytest.mark.parametrize(
    "cluster_name, should_trigger_error",
    [
        ("ThisClusterNameShouldBeRightSize-ContainAHyphen-AndANumber12", False),
        ("ThisClusterNameShouldBeJustOneCharacterTooLongAndShouldntBeOk", True),
        ("2AClusterCanNotBeginByANumber", True),
        ("ClusterCanNotContainUnderscores_LikeThis", True),
        ("ClusterCanNotContainSpaces LikeThis", True),
    ],
)
def test_validate_cluster_name(cluster_name, should_trigger_error, caplog):
    error_msg = (
        "Error: The cluster name can contain only alphanumeric characters (case-sensitive) and hyphens. "
        f"It must start with an alphabetic character and can't be longer than {PCLUSTER_NAME_MAX_LENGTH} characters."
    )
    cluster = dummy_cluster(name=cluster_name)
    failures = cluster._validate_cluster_name()
    assert_that(failures).is_length(1 if should_trigger_error else 0)
    if should_trigger_error:
        assert_that(failures[0].message).is_equal_to(error_msg)
