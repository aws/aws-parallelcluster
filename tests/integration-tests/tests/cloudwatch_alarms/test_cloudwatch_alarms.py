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
import boto3
import pytest
from assertpy import assert_that
from botocore.exceptions import ClientError

@pytest.mark.usefixtures("instance", "os", "scheduler")
@pytest.mark.parametrize("dashboard_enabled", [True, False])
def test_cloudwatch_alarms(
    dashboard_enabled,
    region,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
):
    cluster_config = pcluster_config_reader(dashboard_enabled=str(dashboard_enabled).lower())
    cluster = clusters_factory(cluster_config)
    cw_client = boto3.client("cloudwatch", region_name=region)

    if dashboard_enabled:
        mem_alarm = f"{cluster.cfn_name}_MemAlarm_HeadNode"
        disk_alarm = f"{cluster.cfn_name}_DiskAlarm_HeadNode"
        response = cw_client.describe_alarms(AlarmNamePrefix=cluster.cfn_name)
        alarms = [alarm["AlarmName"] for alarm in response["MetricAlarms"]]
        assert_that(alarms).contains(mem_alarm)
        assert_that(alarms).contains(disk_alarm)
    else:
        try:
            cw_client.describe_alarms(AlarmNamePrefix=cluster.cfn_name)
        except ClientError as e:
            assert_that(e.response["Error"]["Code"]).is_equal_to("ResourceNotFound")

