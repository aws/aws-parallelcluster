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

# TODO move s3_factory.py and awsbatch/utils.py here

from common.boto3.common import AWSExceptionHandler, Boto3Client


class Ec2Client(Boto3Client):
    def __init__(self):
        super().__init__("ec2")

    @AWSExceptionHandler.handle_client_exception
    def describe_instance_type_offerings(self):
        return [
            offering.get("InstanceType")
            for offering in self._paginate_results(self._client.describe_instance_type_offerings)
        ]
