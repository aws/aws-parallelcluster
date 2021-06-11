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
import pytest
from assertpy import assert_that

from pcluster.models.cluster_resources import (
    ExportClusterLogsFiltersParser,
    FiltersParser,
    FiltersParserError,
    ListClusterLogsFiltersParser,
)
from tests.pcluster.aws.dummy_aws_api import mock_aws_api


class TestFiltersParser:
    @pytest.fixture()
    def filters_parser(self):
        return FiltersParser()

    @pytest.mark.parametrize(
        "filters, expected_filters_size, expected_error",
        [
            ("Name=wrong,Value=test", 0, "They must be in the form"),
            ("Name=test1,Values=a ", 1, ""),
            ("Name=test1,Values=a Name=test2,Values=b,c", 2, ""),
        ],
    )
    def test_initialization(self, filters, expected_filters_size, expected_error):
        if expected_error:
            with pytest.raises(FiltersParserError, match=expected_error):
                FiltersParser(filters)
        else:
            filters = FiltersParser(filters)
            assert_that(expected_filters_size).is_equal_to(len(filters.filters_list))


class TestExportClusterLogsFiltersParser:
    @pytest.fixture()
    def export_logs_filters(self):
        return ExportClusterLogsFiltersParser("log_group_name")

    @pytest.mark.parametrize(
        "filters, expected_attrs, expected_error",
        [
            ("Name=wrong,Value=test", {}, "They must be in the form"),
            ("Name=wrong,Values=test", {}, "Filter wrong not supported."),
            ("Name=private-ip-address,Values=10.10.10.10 ", {"log_stream_prefix": "ip-10-10-10-10"}, ""),
            (
                "Name=private-ip-address,Values=10.10.10.10,10.0.0.0",
                {},
                "Filter .* doesn't accept comma separated strings as value",
            ),
            ("Name=end-time,Values=tre", {}, "the expected format is Unix epoch"),
            (
                "Name=private-ip-address,Values=10.10.10.10 "
                "Name=start-time,Values=1623071001 "
                "Name=end-time,Values=1623071001",
                {"log_stream_prefix": "ip-10-10-10-10", "start_time": 1623071001000, "end_time": 1623071001000},
                "",
            ),
        ],
    )
    def test_initialization(self, mocker, filters, expected_attrs, expected_error):
        log_group_name = "log_group_name"
        creation_time_mock = 1623061001000
        mock_aws_api(mocker)
        mocker.patch(
            "pcluster.aws.logs.LogsClient.describe_log_group", return_value={"creationTime": creation_time_mock}
        )

        if expected_error:
            with pytest.raises(FiltersParserError, match=expected_error):
                ExportClusterLogsFiltersParser(log_group_name, filters)
        else:
            export_logs_filters = ExportClusterLogsFiltersParser(log_group_name, filters)

            for attr in expected_attrs:
                assert_that(getattr(export_logs_filters, attr)).is_equal_to(expected_attrs.get(attr))

    @pytest.mark.parametrize(
        "attrs, event_in_window, expected_error",
        [
            # end time after mocked cluster creation time
            ({"end_time": 1623060001000}, True, "Start time must be earlier than end time"),
            (
                {"start_time": 1623072001000, "end_time": 1623071001000},
                True,
                "Start time must be earlier than end time",
            ),
            ({"end_time": 1623071001000}, False, "No log events in the log group"),
        ],
    )
    def test_validate(self, mocker, export_logs_filters, attrs, event_in_window, expected_error):
        log_group_name = "log_group_name"
        creation_time_mock = 1623061001000
        mock_aws_api(mocker)
        describe_log_group_mock = mocker.patch(
            "pcluster.aws.logs.LogsClient.describe_log_group", return_value={"creationTime": creation_time_mock}
        )
        mocker.patch("pcluster.aws.logs.LogsClient.filter_log_events", return_value=event_in_window)

        for attr in attrs:
            setattr(export_logs_filters, attr, attrs[attr])

        if expected_error:
            with pytest.raises(FiltersParserError, match=expected_error):
                export_logs_filters.validate()
        else:
            export_logs_filters.validate()

            if "start_time" not in attrs:
                describe_log_group_mock.assert_called_with(log_group_name)
                assert_that(export_logs_filters.start_time).is_equal_to(creation_time_mock)


class TestListClusterLogsFiltersParser:
    @pytest.mark.parametrize(
        "filters, expected_attrs, expected_error",
        [
            ("Name=wrong,Value=test", {}, "They must be in the form"),
            ("Name=wrong,Values=test", {}, "Filter wrong not supported."),
            ("Name=private-ip-address,Values=10.10.10.10 ", {"log_stream_prefix": "ip-10-10-10-10"}, ""),
            (
                "Name=private-ip-address,Values=10.10.10.10,10.0.0.0",
                {},
                "Filter .* doesn't accept comma separated strings as value",
            ),
        ],
    )
    def test_initialization(self, filters, expected_attrs, expected_error):
        log_group_name = "log_group_name"

        if expected_error:
            with pytest.raises(FiltersParserError, match=expected_error):
                ListClusterLogsFiltersParser(log_group_name, filters)
        else:
            export_logs_filters = ListClusterLogsFiltersParser(log_group_name, filters)

            for attr in expected_attrs:
                assert_that(getattr(export_logs_filters, attr)).is_equal_to(expected_attrs.get(attr))
