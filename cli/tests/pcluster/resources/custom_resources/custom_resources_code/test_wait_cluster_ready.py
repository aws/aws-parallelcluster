# Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with
#  the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

from unittest.mock import patch

import pytest
from assertpy import assert_that

from tests.pcluster.resources.custom_resources.custom_resources_code.utils import (
    _build_lambda_event,
    do_nothing_decorator,
)

# This patching must be executed before the import of the module wait_cluster_ready
# otherwise the module would be loaded with the original retry decorator.
# As a consequence, we need to suppress the linter rule E402 on every import below.
patch("utils.retry_utils.retry", do_nothing_decorator).start()

from pcluster.resources.custom_resources.custom_resources_code.wait_cluster_ready import (  # noqa: E402
    create_update,
    delete,
)
from tests.utils import MockedBoto3Request  # noqa: E402


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.resources.custom_resources.custom_resources_code.wait_cluster_ready.boto3"


def _mocked_request_describe_instances(cluster_name: str, node_types: [str], compute_nodes: [str]):
    return MockedBoto3Request(
        method="describe_instances",
        response={"Reservations": [{"Instances": [{"InstanceId": instance_id} for instance_id in compute_nodes]}]},
        expected_params={
            "Filters": [
                {"Name": "tag:parallelcluster:cluster-name", "Values": [cluster_name]},
                {"Name": "tag:parallelcluster:node-type", "Values": node_types},
                {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
            ],
            "MaxResults": 500,
        },
        generate_error=False,
        error_code=None,
    )


def _mocked_request_batch_get_items(table_name: str, compute_nodes: [str], ddb_records: {}):
    keys = [{"Id": {"S": f"CLUSTER_CONFIG.{instance_id}"}} for instance_id in compute_nodes]
    returned_items = [
        {"Id": {"S": f"CLUSTER_CONFIG.{instance_id}"}, "Data": {"M": ddb_records[instance_id]}}
        for instance_id in ddb_records
    ]
    return MockedBoto3Request(
        method="batch_get_item",
        response={"Responses": {table_name: returned_items}},
        expected_params={
            "RequestItems": {
                table_name: {
                    "Keys": keys,
                },
            },
        },
        generate_error=False,
        error_code=None,
    )


def _event(request_type: str):
    return _build_lambda_event(
        request_type,
        {
            "ClusterName": "CLUSTER_NAME",
            "TableName": "TABLE_NAME",
            "ConfigVersion": "EXPECTED_CONFIG_VERSION",
        },
    )


def _cfn_resource_stub(boto3_stubber):
    boto3_stubber("lambda", [])
    boto3_stubber("events", [])
    boto3_stubber("logs", [])


@pytest.mark.parametrize(
    "compute_nodes, ddb_records, expected_error",
    [
        pytest.param(
            [],
            {},
            None,
            id="Create request with no compute nodes",
        ),
        pytest.param(
            ["i-123456789"],
            {},
            "Check failed due to the following erroneous records:\n"
            "  * missing records (1): ['i-123456789']\n"
            "  * incomplete records (0): []\n"
            "  * wrong records (0): []",
            id="Create request with missing DDB records",
        ),
        pytest.param(
            ["i-123456789"],
            {"i-123456789": {"UNEXPECTED_KEY": {"S": "UNEXPECTED_KEY_VALUE"}}},
            "Check failed due to the following erroneous records:\n"
            "  * missing records (0): []\n"
            "  * incomplete records (1): ['i-123456789']\n"
            "  * wrong records (0): []",
            id="Create request with malformed DDB records",
        ),
        pytest.param(
            ["i-123456789"],
            {"i-123456789": {"cluster_config_version": {"S": "WRONG_CLUSTER_CONFIG_VERSION"}}},
            "Check failed due to the following erroneous records:\n"
            "  * missing records (0): []\n"
            "  * incomplete records (0): []\n"
            "  * wrong records (1): ['i-123456789']",
            id="Create request with wrong cluster config version",
        ),
        pytest.param(
            ["i-123456789"],
            {"i-123456789": {"cluster_config_version": {"S": "EXPECTED_CONFIG_VERSION"}}},
            None,
            id="Create request with correct cluster config version",
        ),
    ],
)
def test_create_update(boto3_stubber, compute_nodes, ddb_records, expected_error):
    _cfn_resource_stub(boto3_stubber)

    boto3_stubber("ec2", [_mocked_request_describe_instances("CLUSTER_NAME", ["Compute"], compute_nodes)])

    boto3_stubber(
        "dynamodb", [_mocked_request_batch_get_items("TABLE_NAME", compute_nodes, ddb_records)] if compute_nodes else []
    )

    if expected_error is not None:
        with pytest.raises(RuntimeError) as exc:
            create_update(_event("Create"), {})
        assert_that(str(exc.value)).is_equal_to(expected_error)
    else:
        create_update(_event("Create"), {})


def test_delete(mocker, boto3_stubber):
    _cfn_resource_stub(boto3_stubber)

    mock_check_compute_nodes_config_version = mocker.patch("wait_cluster_ready.check_compute_nodes_config_version")

    delete(_event("Delete"), {})

    mock_check_compute_nodes_config_version.assert_not_called()
