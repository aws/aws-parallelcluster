# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import json

import pytest
from assertpy import assert_that

from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import load_yaml_dict
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket_object_utils
from tests.pcluster.utils import get_head_node_policy, get_statement_by_sid


@pytest.mark.parametrize(
    "config_file_name,",
    ["config.yaml"],
)
def test_capacity_reservation_id_permissions(mocker, test_datadir, config_file_name):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)

    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_capacity_reservations",
        return_value=[
            {
                "CapacityReservationArn": "arn:partition:service:region:account-id:capacity-reservation/cr-12345",
                "InstanceType": "c5.xlarge",
                "AvailabilityZone": "us-east-1a",
            }
        ],
    )

    input_yaml = load_yaml_dict(test_datadir / config_file_name)

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    head_node_policy = get_head_node_policy(generated_template)
    statement = get_statement_by_sid(policy=head_node_policy, sid="AllowRunningReservedCapacity")
    assert_that(statement["Effect"]).is_equal_to("Allow")
    assert_that(statement["Action"]).is_equal_to("ec2:RunInstances")
    assert_that(json.dumps(statement["Resource"])).contains("capacity-reservation/cr-12345")


@pytest.mark.parametrize(
    "config_file_name,",
    [
        ("config.yaml"),
    ],
)
def test_capacity_reservation_group_arns_permissions(mocker, test_datadir, config_file_name):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)

    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_capacity_reservations",
        return_value=[
            {
                "InstanceType": "c5.xlarge",
                "AvailabilityZone": "us-east-1a",
            }
        ],
    )

    input_yaml = load_yaml_dict(test_datadir / config_file_name)

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    head_node_policy = get_head_node_policy(generated_template)
    statement = get_statement_by_sid(policy=head_node_policy, sid="AllowManagingReservedCapacity")
    assert_that(statement["Effect"]).is_equal_to("Allow")
    assert_that(statement["Action"]).contains_only(
        "ec2:RunInstances", "ec2:CreateFleet", "resource-groups:ListGroupResources"
    )
    assert_that(statement["Resource"]).is_equal_to("cr-12345")
