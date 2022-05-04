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
import datetime
import os
import time

import pytest
from assertpy import assert_that

from pcluster.models.cluster_resources import (
    ClusterInstance,
    ClusterLogsFiltersParser,
    ExportClusterLogsFiltersParser,
    FiltersParserError,
)
from tests.pcluster.aws.dummy_aws_api import mock_aws_api


@pytest.fixture()
def mock_head_node():
    return ClusterInstance({"PrivateDnsName": "ip-10-0-0-102.eu-west2.compute.internal"})


class TestClusterLogsFiltersParser:
    @pytest.mark.parametrize(
        "filters, expected_error",
        [
            (["Name=wrong,Value=test"], "They must be in the form"),
            (["Name=wrong,Values=test"], "Filter wrong not supported."),
            (
                ["Name=private-dns-name,Values=ip-10-10-10-10,ip-10-10-10-11"],
                "Filter .* doesn't accept comma separated strings as value",
            ),
            (
                "Name=private-dns-name,Values=ip-10-10-10-10,ip-10-10-10-11",
                "Invalid filters Name=private-dns-name,Values=ip-10-10-10-10,ip-10-10-10-11. "
                "They must be in the form Name=...,Values=",
            ),
        ],
    )
    def test_initialization_error(self, mock_head_node, filters, expected_error):
        with pytest.raises(FiltersParserError, match=expected_error):
            ClusterLogsFiltersParser(mock_head_node, filters)

    @pytest.mark.parametrize(
        "filters, expected_filters_size, expected_attrs",
        [
            (["Name=private-dns-name,Values=ip-10-10-10-10"], 1, {"log_stream_prefix": "ip-10-10-10-10"}),
            (["Name=node-type,Values=HeadNode"], 1, {"log_stream_prefix": "ip-10-0-0-102"}),
            (None, 0, {"log_stream_prefix": None}),
        ],
    )
    def test_initialization_success(self, mock_head_node, filters, expected_filters_size, expected_attrs):
        logs_filters = ClusterLogsFiltersParser(mock_head_node, filters)

        for attr in expected_attrs:
            assert_that(getattr(logs_filters, attr)).is_equal_to(expected_attrs.get(attr))
        assert_that(expected_filters_size).is_equal_to(len(logs_filters.filters_list))

    @pytest.mark.parametrize(
        "filters, event_in_window, expected_error",
        [
            (
                ["Name=private-dns-name,Values=ip-10-10-10-10", "Name=node-type,Values=HeadNode"],
                True,
                "cannot be set at the same time",
            ),
            (
                ["Name=node-type,Values=Compute"],
                True,
                "The only accepted value for Node Type filter is 'HeadNode'",
            ),
        ],
    )
    def test_validate(self, mock_head_node, filters, event_in_window, expected_error):
        logs_filters = ClusterLogsFiltersParser(mock_head_node, filters)

        if expected_error:
            with pytest.raises(FiltersParserError, match=expected_error):
                logs_filters.validate()
        else:
            logs_filters.validate()


class TestExportClusterLogsFiltersParser:
    @pytest.fixture()
    def export_logs_filters(self, mock_head_node):
        return ExportClusterLogsFiltersParser(mock_head_node, "log_group_name")

    @pytest.mark.parametrize(
        "params, expected_error",
        [
            ({"start_time": "1623071000"}, "Invalid time filter, must be of type 'datetime'"),
            ({"end_time": "1623071000"}, "Invalid time filter, must be of type 'datetime'"),
        ],
    )
    def test_initialization_error(self, mocker, mock_head_node, params, expected_error):
        log_group_name = "log_group_name"
        creation_time_mock = 1623061001000
        mock_aws_api(mocker)
        mocker.patch(
            "pcluster.aws.logs.LogsClient.describe_log_group", return_value={"creationTime": creation_time_mock}
        )

        with pytest.raises(FiltersParserError, match=expected_error):
            ExportClusterLogsFiltersParser(
                mock_head_node,
                log_group_name,
                params.get("start_time", None),
                params.get("end_time", None),
                params.get("filters", None),
            )

    @pytest.mark.parametrize(
        "params, expected_attrs",
        [
            (
                {
                    "start_time": datetime.datetime(2012, 7, 9, tzinfo=datetime.timezone.utc),
                    "end_time": datetime.datetime(2012, 7, 29, tzinfo=datetime.timezone.utc),
                },
                {
                    "log_stream_prefix": None,
                    "start_time": datetime.datetime(2012, 7, 9, tzinfo=datetime.timezone.utc),
                    "end_time": datetime.datetime(2012, 7, 29, tzinfo=datetime.timezone.utc),
                },
            ),
        ],
    )
    def test_initialization_success(self, mock_head_node, params, expected_attrs):
        os.environ["TZ"] = "Europe/London"
        time.tzset()
        log_group_name = "log_group_name"

        export_logs_filters = ExportClusterLogsFiltersParser(
            mock_head_node,
            log_group_name,
            params.get("start_time", None),
            params.get("end_time", None),
            params.get("filters", None),
        )

        for attr in expected_attrs:
            assert_that(getattr(export_logs_filters, attr)).is_equal_to(expected_attrs.get(attr))

    @pytest.mark.parametrize(
        "attrs, event_in_window, expected_error",
        [
            (
                {"end_time": datetime.datetime(2020, 6, 2, tzinfo=datetime.timezone.utc)},
                True,
                "Start time must be earlier than end time",
            ),
            (
                {
                    "start_time": datetime.datetime(2021, 6, 7, tzinfo=datetime.timezone.utc),
                    "end_time": datetime.datetime(2021, 6, 2, tzinfo=datetime.timezone.utc),
                },
                True,
                "Start time must be earlier than end time",
            ),
            (
                {"end_time": datetime.datetime(2021, 7, 9, 22, 45, 22, tzinfo=datetime.timezone.utc)},
                False,
                "No log events in the log group",
            ),
        ],
    )
    def test_validate(self, mocker, mock_head_node, attrs, event_in_window, expected_error):
        log_group_name = "log_group_name"
        creation_time_mock = 1623061001000
        mock_aws_api(mocker)
        describe_log_group_mock = mocker.patch(
            "pcluster.aws.logs.LogsClient.describe_log_group", return_value={"creationTime": creation_time_mock}
        )
        filter_log_events_mock = mocker.patch(
            "pcluster.aws.logs.LogsClient.filter_log_events", return_value=event_in_window
        )

        export_logs_filters = ExportClusterLogsFiltersParser(
            mock_head_node,
            log_group_name,
            attrs.get("start_time", None),
            attrs.get("end_time", None),
            attrs.get("filters", None),
        )

        if expected_error:
            with pytest.raises(FiltersParserError, match=expected_error):
                export_logs_filters.validate()
        else:
            export_logs_filters.validate()
            filter_log_events_mock.assert_called_with(
                log_group_name,
                export_logs_filters.log_stream_prefix,
                export_logs_filters.start_time,
                export_logs_filters.end_time,
            )

            if "start_time" not in attrs:
                describe_log_group_mock.assert_called_with(log_group_name)
                assert_that(export_logs_filters.start_time).is_equal_to(creation_time_mock)
