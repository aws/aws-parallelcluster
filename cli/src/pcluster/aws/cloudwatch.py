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

from pcluster.aws.common import AWSExceptionHandler, Boto3Client
from pcluster.utils import get_start_end_timestamp


class CloudWatchClient(Boto3Client):
    """Cloudwatch Boto3 client."""

    def __init__(self):
        super().__init__("cloudwatch")

    @AWSExceptionHandler.handle_client_exception
    def describe_alarms(self, alarm_names):
        """Describe alarms."""
        return self._client.describe_alarms(AlarmNames=alarm_names)

    @AWSExceptionHandler.handle_client_exception
    def get_alarms_with_states(self, alarm_names):
        """Get alarms and their current state values"""
        metric_alarms = self.describe_alarms(alarm_names).get("MetricAlarms", [])
        return [{"alarm_type": alarm["AlarmName"], "alarm_state": alarm["StateValue"]} for alarm in metric_alarms]

    def _get_metric_data(self, cluster_name, metric_name, start_timestamp, end_timestamp):
        """Get the cloudwatch metric data results"""
        metrics_response = self._client.get_metric_data(
            MetricDataQueries=[
                {
                    "Id": "get_metric_data",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "ParallelCluster",
                            "MetricName": metric_name,
                            "Dimensions": [
                                {
                                    "Name": "ClusterName",
                                    "Value": cluster_name,
                                }
                            ],
                        },
                        "Period": 300,
                        "Stat": "Sum",
                    },
                },
            ],
            StartTime=start_timestamp,
            EndTime=end_timestamp,
        )
        metric_values = metrics_response["MetricDataResults"][0].get("Values", [])

        return metric_values

    @AWSExceptionHandler.handle_client_exception
    def get_cluster_health_metrics_values(self, cluster_name):
        cluster_health_metrics = [
            "IamPolicyErrors",
            "VcpuLimitErrors",
            "VolumeLimitErrors",
            "InsufficientCapacityErrors",
            "OtherInstanceLaunchFailures",
            "InstanceBootstrapTimeoutErrors",
            "EC2HealthCheckErrors",
            "ScheduledEventHealthCheckErrors",
            "NoCorrespondingInstanceErrors",
            "SlurmNodeNotRespondingErrors",
            "MaxDynamicNodeIdleTime",
            "GpuHealthCheckFailures",
        ]

        # query for the past 5 minutes
        start_timestamp, end_timestamp = get_start_end_timestamp(minutes=5)

        metrics_objects = []
        for metric_name in cluster_health_metrics:
            metric_values = self._get_metric_data(cluster_name, metric_name, start_timestamp, end_timestamp)
            metric_value = sum(metric_values) if metric_values else None
            if metric_value is not None and metric_value != 0:
                metrics_objects.append({"metric_type": metric_name, "metric_value": metric_value})

        return metrics_objects
