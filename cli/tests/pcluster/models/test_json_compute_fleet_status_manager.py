import os

import pytest
from assertpy import assert_that

from pcluster.aws.common import AWSClientError
from pcluster.models.compute_fleet_status_manager import (
    ComputeFleetStatus,
    ComputeFleetStatusManager,
    JsonComputeFleetStatusManager,
)


class TestComputeFleetStatusManager:
    @pytest.fixture
    def compute_fleet_status_manager(self):
        if "AWS_DEFAULT_REGION" not in os.environ:
            # We need to provide a region to boto3 to avoid no region exception.
            # Which region to provide is arbitrary.
            os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        status_manager = JsonComputeFleetStatusManager("cluster-name")

        return status_manager

    @pytest.mark.parametrize(
        "get_item_response, fallback, expected_status",
        [
            ({"Item": {"Id": "COMPUTE_FLEET", "Data": {"status": "RUNNING"}}}, None, ComputeFleetStatus.RUNNING),
            (
                {},
                ComputeFleetStatus.STOPPED,
                ComputeFleetStatus.STOPPED,
            ),
            (
                Exception,
                ComputeFleetStatus.STOPPED,
                ComputeFleetStatus.STOPPED,
            ),
        ],
        ids=["success", "empty_response", "exception"],
    )
    def test_get_status_with_last_updated_time(
        self, mocker, compute_fleet_status_manager, get_item_response, fallback, expected_status
    ):
        if get_item_response is Exception:
            get_item_mock = mocker.patch("pcluster.aws.dynamo.DynamoResource.get_item", side_effect=get_item_response)
        else:
            get_item_mock = mocker.patch("pcluster.aws.dynamo.DynamoResource.get_item", return_value=get_item_response)
        status, _ = compute_fleet_status_manager.get_status_with_last_updated_time(fallback)
        assert_that(status).is_equal_to(expected_status)
        get_item_mock.assert_called_with("parallelcluster-cluster-name", {"Id": "COMPUTE_FLEET"})

    @pytest.mark.parametrize(
        "update_item_response, expected_exception",
        [
            (
                {},
                None,
            ),
            (
                AWSClientError("function", "message", "ConditionalCheckFailedException"),
                ComputeFleetStatusManager.ConditionalStatusUpdateFailed,
            ),
            (Exception(), Exception),
        ],
        ids=["success", "conditional_check_failed", "exception"],
    )
    def test_put_status(self, mocker, compute_fleet_status_manager, update_item_response, expected_exception):
        if isinstance(update_item_response, Exception):
            mocker.patch("pcluster.aws.dynamo.DynamoResource.update_item", side_effect=update_item_response)
            with pytest.raises(expected_exception):
                compute_fleet_status_manager._put_status(ComputeFleetStatus.STARTING, ComputeFleetStatus.RUNNING)
        else:
            mocker.patch("pcluster.aws.dynamo.DynamoResource.update_item", return_value=update_item_response)
            compute_fleet_status_manager._put_status(ComputeFleetStatus.STARTING, ComputeFleetStatus.RUNNING)
