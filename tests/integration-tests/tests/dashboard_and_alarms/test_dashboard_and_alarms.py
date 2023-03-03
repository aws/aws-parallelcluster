# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import datetime
import math
import time
import boto3
import pytest
from assertpy import assert_that
from botocore.exceptions import ClientError


@pytest.mark.usefixtures("instance", "os", "scheduler")
@pytest.mark.parametrize("dashboard_enabled, cw_log_enabled", [(True, True), (True, False), (False, False)])
def test_dashboard_and_alarms(
    dashboard_enabled,
    cw_log_enabled,
    region,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
):
    cluster_config = pcluster_config_reader(
        dashboard_enabled=str(dashboard_enabled).lower(),
        cw_log_enabled=str(cw_log_enabled).lower(),
    )
    cluster = clusters_factory(cluster_config)
    cw_client = boto3.client("cloudwatch", region_name=region)
    headnode_instance_id = cluster.get_cluster_instance_ids(node_type="HeadNode")[0]
    compute_instance_ids = cluster.get_cluster_instance_ids(node_type="Compute")

    # test CWAgent metrics
    # sleep for 2 minutes to ensure we can get metrics data
    time.sleep(60 * 2)
    start_timestamp, end_timestamp = _get_start_end_timestamp(minutes=2)
    metrics_response_headnode = _get_metric_data(headnode_instance_id, cw_client, start_timestamp, end_timestamp)
    mem_values = _get_metric_data_values(metrics_response_headnode, "mem")
    disk_values = _get_metric_data_values(metrics_response_headnode, "disk")
    assert_that(mem_values).is_not_empty()
    assert_that(disk_values).is_not_empty()

    if compute_instance_ids:
        metrics_response_compute = _get_metric_data(compute_instance_ids[0], cw_client, start_timestamp, end_timestamp)
        mem_values = _get_metric_data_values(metrics_response_compute, "mem")
        disk_values = _get_metric_data_values(metrics_response_compute, "disk")
        assert_that(mem_values).is_empty()
        assert_that(disk_values).is_empty()

    # test dashboard and alarms
    dashboard_name = "{0}-{1}".format(cluster.cfn_name, region)
    if dashboard_enabled:
        # test dashboard
        dashboard_response = cw_client.get_dashboard(DashboardName=dashboard_name)
        assert_that(dashboard_response["DashboardName"]).is_equal_to(dashboard_name)
        if cw_log_enabled:
            assert_that(dashboard_response["DashboardBody"]).contains("Head Node Logs")
        else:
            assert_that(dashboard_response["DashboardBody"]).does_not_contain("Head Node Logs")

        # test alarms
        mem_alarm_name = f"{cluster.cfn_name}_MemAlarm_HeadNode"
        disk_alarm_name = f"{cluster.cfn_name}_DiskAlarm_HeadNode"
        alarm_response = cw_client.describe_alarms(AlarmNamePrefix=cluster.cfn_name)
        mem_alarms = _get_alarm_records(alarm_response, mem_alarm_name)
        disk_alarms = _get_alarm_records(alarm_response, disk_alarm_name)
        _verify_alarms(mem_alarms, "mem_used_percent", headnode_instance_id)
        _verify_alarms(disk_alarms, "disk_used_percent", headnode_instance_id)

    else:
        # test dashboard
        try:
            cw_client.get_dashboard(DashboardName=dashboard_name)
        except ClientError as e:
            assert_that(e.response["Error"]["Code"]).is_equal_to("ResourceNotFound")

        # test alarms
        alarm_response = cw_client.describe_alarms(AlarmNamePrefix=cluster.cfn_name)
        assert_that(alarm_response["MetricAlarms"]).is_empty()


def _get_start_end_timestamp(minutes):
    """
    The end time for query will be the current time rounded to minute that is not earlier than the current time (ceil).
    For instance, if the current time is 09:34:20, then the end time for query will be 09:35:00.
    This is because our metrics have a period of 1 minute, and according to public documentation of GetMetricData:
    "For better performance, specify StartTime and EndTime values that align with the value of the metric's Period
    and sync up with the beginning and end of an hour."
    Reference: https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_GetMetricData.html
    """
    now_utc = datetime.datetime.now().astimezone(datetime.timezone.utc)
    end_timestamp_ceil = math.ceil(now_utc.timestamp() / 60) * 60
    end_dt = datetime.datetime.fromtimestamp(end_timestamp_ceil)
    start_dt = end_dt - datetime.timedelta(minutes=minutes)
    start_timestamp = start_dt.timestamp()
    return start_timestamp, end_timestamp_ceil


def _get_metric_data(instance_id, cw_client, start_timestamp, end_timestamp):
    metrics_response = cw_client.get_metric_data(
        MetricDataQueries=[
            {
                "Id": "mem",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "CWAgent",
                        "MetricName": "mem_used_percent",
                        "Dimensions": [
                            {
                                "Name": "InstanceId",
                                "Value": instance_id,
                            }
                        ],
                    },
                    "Period": 60,
                    "Stat": "Maximum",
                },
            },
            {
                "Id": "disk",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "CWAgent",
                        "MetricName": "disk_used_percent",
                        "Dimensions": [
                            {
                                "Name": "InstanceId",
                                "Value": instance_id,
                            },
                            {"Name": "path", "Value": "/"},
                        ],
                    },
                    "Period": 60,
                    "Stat": "Maximum",
                },
            },
        ],
        StartTime=start_timestamp,
        EndTime=end_timestamp,
    )
    return metrics_response


def _get_metric_data_values(response, query_id):
    return [record["Values"] for record in response["MetricDataResults"] if record["Id"] == query_id]


def _get_alarm_records(response, alarm_name):
    return [alarm for alarm in response["MetricAlarms"] if alarm["AlarmName"] == alarm_name]


def _verify_alarms(alarms, metric_name, instance_id):
    assert_that(alarms).is_length(1)
    assert_that(alarms[0]["MetricName"]).is_equal_to(metric_name)
    assert_that(alarms[0]["Namespace"]).is_equal_to("CWAgent")
    assert_that(alarms[0]["Statistic"]).is_equal_to("Maximum")
    assert_that(alarms[0]["Period"]).is_equal_to(60)
    assert_that(alarms[0]["Threshold"]).is_equal_to(90)
    assert_that(alarms[0]["ComparisonOperator"]).is_equal_to("GreaterThanThreshold")
    if metric_name == "mem_used_percent":
        assert_that(alarms[0]["Dimensions"]).contains({"Name": "InstanceId", "Value": instance_id})
    elif metric_name == "disk_used_percent":
        assert_that(alarms[0]["Dimensions"]).contains({"Name": "path", "Value": "/"}).contains(
            {"Name": "InstanceId", "Value": instance_id}
        )
