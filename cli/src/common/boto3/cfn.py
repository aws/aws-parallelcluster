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
import json

from common.boto3.common import AWSClientError, AWSExceptionHandler, Boto3Client


class CfnClient(Boto3Client):
    """Implement CFN Boto3 client."""

    def __init__(self):
        super().__init__("cloudformation")

    @AWSExceptionHandler.handle_client_exception
    def create_stack(self, stack_name: str, template_url: str, disable_rollback: bool, tags: list):
        """Create CFN stack by using the given template."""
        return self._client.create_stack(
            StackName=stack_name,
            TemplateURL=template_url,
            Capabilities=["CAPABILITY_IAM"],
            DisableRollback=disable_rollback,
            Tags=tags,
        )

    @AWSExceptionHandler.handle_client_exception
    def delete_stack(self, stack_name: str):
        """Delete CFN stack."""
        return self._client.delete_stack(StackName=stack_name)

    @AWSExceptionHandler.handle_client_exception
    def update_stack(self, stack_name: str, updated_template: str, params: list):
        """Update CFN stack."""
        return self._client.update_stack(
            StackName=stack_name,
            TemplateBody=json.dumps(updated_template, indent=2),  # Indent so it looks nice in the console
            Parameters=params,
            Capabilities=["CAPABILITY_IAM"],
        )

    @AWSExceptionHandler.handle_client_exception
    def describe_stack(self, stack_name: str):
        """Get information for the given stack."""
        return self._client.describe_stacks(StackName=stack_name).get("Stacks")[0]

    def stack_exists(self, stack_name: str):
        """Return a boolean describing whether or not a stack by the given name exists."""
        try:
            self.describe_stack(stack_name)
            return True
        except AWSClientError as e:
            if f"Stack with id {stack_name} does not exist" in str(e):
                return False
            raise e
