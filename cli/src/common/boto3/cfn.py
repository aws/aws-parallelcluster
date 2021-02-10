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

from common.boto3.common import AWSExceptionHandler, Boto3Client


class CfnClient(Boto3Client):
    """Implement CFN Boto3 client."""

    def __init__(self):
        super().__init__("cfn")

    @AWSExceptionHandler.handle_client_exception
    def create_stack(self, stack_name, template_url, disable_rollback, tags):
        """Create CFN stack by using the given template."""
        return self._client.create_stack(
            StackName=stack_name,
            TemplateURL=template_url,
            Capabilities=["CAPABILITY_IAM"],
            DisableRollback=disable_rollback,
            Tags=tags,
        )
