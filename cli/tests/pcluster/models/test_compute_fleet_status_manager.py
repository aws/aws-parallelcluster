import logging
import os

import pytest
from assertpy import assert_that

from pcluster.aws.common import AWSClientError
from pcluster.models.compute_fleet_status_manager import ComputeFleetStatus, ComputeFleetStatusManager


class TestComputeFleetStatusManager:
    @pytest.fixture
    def compute_fleet_status_manager(self):
        if "AWS_DEFAULT_REGION" not in os.environ:
            # We need to provide a region to boto3 to avoid no region exception.
            # Which region to provide is arbitrary.
            os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        status_manager = ComputeFleetStatusManager("cluster-name")

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
    def test_get_status(self, mocker, compute_fleet_status_manager, get_item_response, fallback, expected_status):
        if get_item_response is Exception:
            get_item_mock = mocker.patch("pcluster.aws.dynamo.DynamoResource.get_item", side_effect=get_item_response)
        else:
            get_item_mock = mocker.patch("pcluster.aws.dynamo.DynamoResource.get_item", return_value=get_item_response)
        status = compute_fleet_status_manager.get_status(fallback)
        assert_that(status).is_equal_to(expected_status)
        get_item_mock.assert_called_with("parallelcluster-cluster-name", {"Id": "COMPUTE_FLEET"})

    @pytest.mark.parametrize(
        "put_item_response, expected_exception",
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
    def test_put_status(self, mocker, compute_fleet_status_manager, put_item_response, expected_exception):
        if isinstance(put_item_response, Exception):
            mocker.patch("pcluster.aws.dynamo.DynamoResource.put_item", side_effect=put_item_response)
            with pytest.raises(expected_exception):
                compute_fleet_status_manager.put_status(ComputeFleetStatus.STARTING, ComputeFleetStatus.RUNNING)
        else:
            mocker.patch("pcluster.aws.dynamo.DynamoResource.put_item", return_value=put_item_response)
            compute_fleet_status_manager.put_status(ComputeFleetStatus.STARTING, ComputeFleetStatus.RUNNING)

    @pytest.mark.parametrize(
        "request_status, get_status_responses, update_status_responses, expected_exception, expected_error_message,"
        " wait_for_transitions",
        [
            (
                ComputeFleetStatus.START_REQUESTED,
                [ComputeFleetStatus.UNKNOWN],
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
                    ComputeFleetStatus.PROTECTED,
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
                ComputeFleetStatus.STOP_REQUESTED,
                [
                    ComputeFleetStatus.PROTECTED,
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
        caplog.set_level(logging.WARNING, logger="pcluster")
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
