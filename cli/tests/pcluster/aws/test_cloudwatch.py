# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from pcluster.aws.cloudwatch import CloudWatchClient
from pcluster.utils import get_start_end_timestamp
from tests.utils import MockedBoto3Request


@pytest.fixture()
def boto3_stubber_path():
    return "pcluster.aws.common.boto3"


@pytest.mark.parametrize(
    "alarm_names, describe_alarms_response, expected_result",
    [
        (
            ["test_alarm"],
            {"MetricAlarms": [{"AlarmName": "test_alarm", "StateValue": "OK"}]},
            [{"alarm_type": "test_alarm", "alarm_state": "OK"}],
        ),
        ([], {}, []),
        (["not_existing_alarm"], {"MetricAlarms": [], "CompositeAlarms": []}, []),
    ],
    ids=["Alarm_OK", "Empty", "Not_existing_alarm"],
)
def test_get_alarms_with_states(boto3_stubber, alarm_names, describe_alarms_response, expected_result):
    mocked_requests = [
        MockedBoto3Request(
            method="describe_alarms", response=describe_alarms_response, expected_params={"AlarmNames": alarm_names}
        )
    ]
    boto3_stubber("cloudwatch", mocked_requests)
    result = CloudWatchClient().get_alarms_with_states(alarm_names)
    assert_that(result).is_equal_to(expected_result)


def get_metric_values_mocked_request(cluster_name, metric_name, start_timestamp, end_timestamp, values):
    return MockedBoto3Request(
        method="get_metric_data",
        response={"MetricDataResults": [{"Values": values}]},
        expected_params={
            "MetricDataQueries": [
                {
                    "Id": "get_metric_data",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "ParallelCluster",
                            "MetricName": metric_name,
                            "Dimensions": [
                                {"Name": "ClusterName", "Value": cluster_name},
                            ],
                        },
                        "Period": 300,
                        "Stat": "Sum",
                    },
                },
            ],
            "StartTime": start_timestamp,
            "EndTime": end_timestamp,
        },
    )


def test_get_cluster_health_metrics_values(boto3_stubber):
    cluster_name = "test_cluster"
    # create a dictionary to mock metrics and their values
    test_metrics_values = {
        "IamPolicyErrors": [0],
        "VcpuLimitErrors": [0],
        "VolumeLimitErrors": [0],
        "InsufficientCapacityErrors": [3, 3, 3],
        "OtherInstanceLaunchFailures": [1],
        "InstanceBootstrapTimeoutErrors": [],
        "EC2HealthCheckErrors": [],
        "ScheduledEventHealthCheckErrors": [],
        "NoCorrespondingInstanceErrors": [],
        "SlurmNodeNotRespondingErrors": [],
        "MaxDynamicNodeIdleTime": [40],
        "GpuHealthCheckFailures": [0],
    }

    expected_result = [
        {"metric_type": key, "metric_value": sum(values)}
        for key, values in test_metrics_values.items()
        if sum(values) != 0
    ]

    # query for the past 5 minutes
    start_timestamp, end_timestamp = get_start_end_timestamp(minutes=5)

    mocked_requests = []
    for metric_name, values in test_metrics_values.items():
        mocked_request = get_metric_values_mocked_request(
            cluster_name, metric_name, start_timestamp, end_timestamp, values
        )
        mocked_requests.append(mocked_request)

    boto3_stubber("cloudwatch", mocked_requests)
    result = CloudWatchClient().get_cluster_health_metrics_values(cluster_name)
    assert_that(result == expected_result)
