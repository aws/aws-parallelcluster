import os

import boto3
import pytest
from assertpy import assert_that

from pcluster.cli_commands.compute_fleet_status_manager import ComputeFleetStatus, ComputeFleetStatusManager


class TestComputeFleetStatusManager:
    @pytest.fixture
    def compute_fleet_status_manager(self, mocker):
        if "AWS_DEFAULT_REGION" not in os.environ:
            # We need to provide a region to boto3 to avoid no region exception.
            # Which region to provide is arbitrary.
            os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        status_manager = ComputeFleetStatusManager("cluster-name")
        mocker.patch.object(status_manager, "_table")

        return status_manager

    @pytest.mark.parametrize(
        "get_item_response, fallback, expected_status",
        [
            ({"Item": {"Id": "COMPUTE_FLEET", "Status": "RUNNING"}}, None, ComputeFleetStatus.RUNNING),
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
            (
                {},
                None,
            ),
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
    def test_put_status(self, compute_fleet_status_manager, put_item_response, expected_exception):
        if isinstance(put_item_response, Exception):
            compute_fleet_status_manager._table.put_item.side_effect = put_item_response
            with pytest.raises(expected_exception):
                compute_fleet_status_manager.put_status(ComputeFleetStatus.STARTING, ComputeFleetStatus.RUNNING)
        else:
            compute_fleet_status_manager._table.put_item.return_value = put_item_response
            compute_fleet_status_manager.put_status(ComputeFleetStatus.STARTING, ComputeFleetStatus.RUNNING)

    @pytest.mark.parametrize(
        "request_status, get_status_responses, update_status_responses, expected_exception, expected_error_message,"
        " wait_for_transitions",
        [
            (
                ComputeFleetStatus.START_REQUESTED,
                [None],
                [],
                Exception,
                "Could not retrieve compute fleet status",
                True,
            ),
            (ComputeFleetStatus.START_REQUESTED, [ComputeFleetStatus.RUNNING], [], None, None, True),
            (
                ComputeFleetStatus.START_REQUESTED,
                [
                    ComputeFleetStatus.STOPPED,
                    ComputeFleetStatus.START_REQUESTED,
                    ComputeFleetStatus.STARTING,
                    ComputeFleetStatus.RUNNING,
                ],
                [None],
                None,
                None,
                True,
            ),
            (
                ComputeFleetStatus.START_REQUESTED,
                [
                    ComputeFleetStatus.STOPPED,
                    ComputeFleetStatus.START_REQUESTED,
                    ComputeFleetStatus.STARTING,
                    ComputeFleetStatus.STOPPED,
                ],
                [None],
                Exception,
                "Unexpected final state STOPPED probably due to a concurrent status update request",
                True,
            ),
            (
                ComputeFleetStatus.STOP_REQUESTED,
                [
                    ComputeFleetStatus.RUNNING,
                    ComputeFleetStatus.STOP_REQUESTED,
                    ComputeFleetStatus.STOPPING,
                    ComputeFleetStatus.STOPPED,
                ],
                [None],
                None,
                None,
                True,
            ),
            (
                ComputeFleetStatus.STOP_REQUESTED,
                [ComputeFleetStatus.RUNNING, ComputeFleetStatus.STOP_REQUESTED, ComputeFleetStatus.STARTING],
                [None],
                Exception,
                "Unexpected final state STARTING probably due to a concurrent status update request",
                True,
            ),
            (
                ComputeFleetStatus.STOP_REQUESTED,
                [ComputeFleetStatus.RUNNING],
                [ComputeFleetStatusManager.ConditionalStatusUpdateFailed],
                ComputeFleetStatusManager.ConditionalStatusUpdateFailed,
                None,
                True,
            ),
            (ComputeFleetStatus.START_REQUESTED, [ComputeFleetStatus.STOPPED], [None], None, None, False),
        ],
    )
    def test_update_status(
        self,
        mocker,
        caplog,
        compute_fleet_status_manager,
        request_status,
        get_status_responses,
        update_status_responses,
        expected_exception,
        expected_error_message,
        wait_for_transitions,
    ):
        get_status_mock = mocker.patch.object(
            compute_fleet_status_manager, "get_status", side_effect=get_status_responses
        )
        update_status_mock = mocker.patch.object(
            compute_fleet_status_manager, "put_status", side_effect=update_status_responses
        )
        mocker.patch("time.sleep")

        final_status = (
            ComputeFleetStatus.STOPPED
            if request_status == ComputeFleetStatus.STOP_REQUESTED
            else ComputeFleetStatus.RUNNING
        )
        in_progress_status = (
            ComputeFleetStatus.STOPPING
            if request_status == ComputeFleetStatus.STOP_REQUESTED
            else ComputeFleetStatus.STARTING
        )
        if expected_exception:
            with pytest.raises(expected_exception) as e:
                compute_fleet_status_manager.update_status(
                    request_status, in_progress_status, final_status, wait_transition=wait_for_transitions
                )
            if expected_error_message:
                assert_that(str(e.value)).contains(expected_error_message)
        else:
            compute_fleet_status_manager.update_status(
                request_status, in_progress_status, final_status, wait_transition=wait_for_transitions
            )

        assert_that(update_status_mock.call_count).is_equal_to(len(update_status_responses))
        assert_that(get_status_mock.call_count).is_equal_to(len(get_status_responses))
        assert_that(caplog.text).is_empty()
