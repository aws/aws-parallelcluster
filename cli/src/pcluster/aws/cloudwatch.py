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


class CloudWatchClient(Boto3Client):
    """Cloudwatch Boto3 client."""

    def __init__(self):
        super().__init__("cloudwatch")

    @AWSExceptionHandler.handle_client_exception
    def describe_alarms(self, alarm_names):
        """Describe alarms."""
        return self._client.describe_alarms(AlarmNames=alarm_names)

    @AWSExceptionHandler.handle_client_exception
    def get_alarms_in_alarm(self, alarm_names):
        """Get alarms with the state value of alarm."""
        metric_alarms = self.describe_alarms(alarm_names).get("MetricAlarms", [])
        return [
            {"alarm_type": alarm["AlarmName"], "alarm_state": alarm["StateValue"]}
            for alarm in metric_alarms
            if alarm["StateValue"] == "ALARM"
        ]
