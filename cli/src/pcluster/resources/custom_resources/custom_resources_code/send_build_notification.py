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
import time
from http.client import HTTPSConnection
from urllib.parse import urlsplit, urlunsplit


def handler(event, context):  # pylint: disable=unused-argument
    """Handle CodeBuild build status changes and send notifications to CFN WaitCondition."""
    print("CodeBuild event: %s" % json.dumps(event))
    environment_variables = event["detail"]["additional-information"]["environment"]["environment-variables"]
    notification_url = next(var.get("value") for var in environment_variables if var.get("name") == "NOTIFICATION_URL")
    succeeded = event["detail"]["build-status"] == "SUCCEEDED"
    data = json.dumps(
        {
            "Status": "SUCCESS" if succeeded else "FAILURE",
            "Reason": "Build Complete" if succeeded else "Build Failed. See the CodeBuild logs for further details.",
            "UniqueId": event["detail"]["build-id"],
            "Data": "Build has completed.",
        }
    )
    print(f"Notification URL: {notification_url}")
    print(f"Notification data: {data}")

    # This function returns a 5-tuple: (addressing scheme, network location, path, query, fragment identifier)
    split_url = urlsplit(notification_url)
    host = split_url.netloc
    # Building the url without scheme and hostname
    url = urlunsplit(("", "", *split_url[2:]))
    while True:
        try:
            connection = HTTPSConnection(host)  # nosec nosemgrep
            connection.request(
                method="PUT", url=url, body=data, headers={"Content-Type": "", "content-length": str(len(data))}
            )
            response = connection.getresponse()
            print(f"CloudFormation returned status code: {response.reason}")
            break
        except Exception as e:
            print(f"Unexpected failure sending response to CloudFormation {e}")
            time.sleep(5)
