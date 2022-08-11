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
import time

import boto3
import pytest
from assertpy import assert_that
from botocore.exceptions import ClientError
from remote_command_executor import RemoteCommandExecutor
from utils import check_metric_data_query, retrieve_metric_data


@pytest.mark.usefixtures("instance", "os", "scheduler")
@pytest.mark.parametrize(
    "dashboard_enabled, cw_log_enabled, enabled_error_metrics",
    [(True, True, True), (True, False, True), (False, False, False)],
)
def test_dashboard(
    dashboard_enabled,
    cw_log_enabled,
    enabled_error_metrics,
    region,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    s3_bucket_factory,
    scheduler_commands_factory,
):
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "preinstall.sh"), "scripts/preinstall.sh")
    cluster_config = pcluster_config_reader(
        dashboard_enabled=str(dashboard_enabled).lower(),
        cw_log_enabled=str(cw_log_enabled).lower(),
        enabled_error_metrics=str(enabled_error_metrics).lower(),
        bucket=bucket_name,
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    slurm_commands = scheduler_commands_factory(remote_command_executor)
    cw_client = boto3.client("cloudwatch", region_name=region)
    dashboard_name = "{0}-{1}".format(cluster.cfn_name, region)

    if dashboard_enabled:
        response = cw_client.get_dashboard(DashboardName=dashboard_name)
        assert_that(response["DashboardName"]).is_equal_to(dashboard_name)
        if cw_log_enabled:
            assert_that(response["DashboardBody"]).contains("Head Node Logs")
            if enabled_error_metrics:
                assert_that(response["DashboardBody"]).contains("Metrics for Common Errors")
                assert_that(response["DashboardBody"]).contains("Custom Script Errors")
                # Get the metric data for applicable metrics
                metric_name = [
                    "Cannot retrieve custom script",
                    "Error With Custom Script",
                    "Terminated EC2 compute node before job submission",
                ]
                unique_name = ["retrieve", "error", "terminate"]
                period_sec = 60
                collection_time_min = 12
                # Delete script from file
                s3 = boto3.resource("s3")
                s3.Object(bucket_name, "preinstall.sh").delete()
                # Submit job
                slurm_commands.submit_command_and_assert_job_accepted(
                    submit_command_args={
                        "command": "sleep 150",
                        "nodes": 1,
                        "slots": 1,
                    }
                )
                # Check if metric value has increased
                time.sleep(600)
                response = retrieve_metric_data(unique_name, cluster.name, metric_name, period_sec, collection_time_min)
                check_metric_data_query(response, 1)
            else:
                assert_that(response["DashboardBody"]).does_not_contain("Metrics for Common Errors")
        else:
            assert_that(response["DashboardBody"]).does_not_contain("Head Node Logs")
    else:
        try:
            cw_client.get_dashboard(DashboardName=dashboard_name)
        except ClientError as e:
            assert_that(e.response["Error"]["Code"]).is_equal_to("ResourceNotFound")
