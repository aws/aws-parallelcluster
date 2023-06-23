import logging
import os

import pytest
from assertpy import assert_that

from pcluster.models.compute_fleet_status_manager import (
    ComputeFleetStatus,
    ComputeFleetStatusManager,
    JsonComputeFleetStatusManager,
    PlainTextComputeFleetStatusManager,
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
            compute_fleet_status_manager, "_put_status", side_effect=update_status_responses
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

    @pytest.mark.parametrize(
        "version, expected_compute_fleet_status_manager_instance",
        [
            ("3.2.0", JsonComputeFleetStatusManager),
            ("3.1.1", PlainTextComputeFleetStatusManager),
        ],
    )
    def test_get_manager(self, version, expected_compute_fleet_status_manager_instance):
        compute_fleet_status_manager = ComputeFleetStatusManager.get_manager("cluster-name", version)
        assert_that(compute_fleet_status_manager).is_instance_of(expected_compute_fleet_status_manager_instance)
