import boto3
import pytest
from assertpy import assert_that

from pcluster.cli_commands.compute_fleet_status_manager import ComputeFleetStatus, ComputeFleetStatusManager


class TestComputeFleetStatusManager:
    @pytest.fixture
    def compute_fleet_status_manager(self, mocker):
        status_manager = ComputeFleetStatusManager("cluster-name")
        mocker.patch.object(status_manager, "_table")

        return status_manager

    @pytest.mark.parametrize(
        "get_item_response, fallback, expected_status",
        [
            ({"Item": {"Id": "COMPUTE_FLEET", "Status": "RUNNING"}}, None, ComputeFleetStatus.RUNNING),
            ({}, ComputeFleetStatus.STOPPED, ComputeFleetStatus.STOPPED,),
            (Exception, ComputeFleetStatus.STOPPED, ComputeFleetStatus.STOPPED,),
        ],
        ids=["success", "empty_response", "exception"],
    )
    def test_get_status(self, compute_fleet_status_manager, get_item_response, fallback, expected_status):
        if get_item_response is Exception:
            compute_fleet_status_manager._table.get_item.side_effect = get_item_response
        else:
            compute_fleet_status_manager._table.get_item.return_value = get_item_response
        status = compute_fleet_status_manager.get_status(fallback)
        assert_that(status).is_equal_to(expected_status)
        compute_fleet_status_manager._table.get_item.assert_called_with(
            ConsistentRead=True, Key={"Id": "COMPUTE_FLEET"}
        )

    @pytest.mark.parametrize(
        "put_item_response, expected_exception",
        [
            ({}, None,),
            (
                boto3.client("dynamodb", region_name="us-east-1").exceptions.ConditionalCheckFailedException(
                    {"Error": {}}, {}
                ),
                ComputeFleetStatusManager.ConditionalStatusUpdateFailed,
            ),
            (Exception(), Exception),
        ],
        ids=["success", "conditional_check_failed", "exception"],
    )
    def test_update_status(self, compute_fleet_status_manager, put_item_response, expected_exception):
        if isinstance(put_item_response, Exception):
            compute_fleet_status_manager._table.put_item.side_effect = put_item_response
            with pytest.raises(expected_exception):
                compute_fleet_status_manager.update_status(ComputeFleetStatus.STARTING, ComputeFleetStatus.RUNNING)
        else:
            compute_fleet_status_manager._table.put_item.return_value = put_item_response
            compute_fleet_status_manager.update_status(ComputeFleetStatus.STARTING, ComputeFleetStatus.RUNNING)
