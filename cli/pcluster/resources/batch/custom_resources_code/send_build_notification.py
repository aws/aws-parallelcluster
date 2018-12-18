# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with
#  the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import json
import os

from botocore.vendored import requests


def handler(event, context):
    """Handle CodeBuild build status changes and send notifications to CFN WaitCondition."""
    print("CodeBuild event: %s" % json.dumps(event))
    notification_url = os.environ["NOTIFICATION_URL"]
    succeeded = event["detail"]["build-status"] == "SUCCEEDED"
    data = json.dumps(
        {
            "Status": "SUCCESS" if succeeded else "FAILURE",
            "Reason": "Build Complete" if succeeded else "Build Failed. See the CodeBuild logs for further details.",
            "UniqueId": event["detail"]["build-id"],
            "Data": "Build has completed.",
        }
    )
    print("Notification URL: %s" % notification_url)
    print("Notification data: %s" % data)
    requests.put(notification_url, data=data, headers={"Content-Type": ""})
