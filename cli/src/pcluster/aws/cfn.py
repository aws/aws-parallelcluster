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
import logging

from botocore.exceptions import ClientError

from pcluster.aws.aws_resources import StackInfo
from pcluster.aws.common import AWSClientError, AWSExceptionHandler, Boto3Client, StackNotFoundError
from pcluster.constants import PCLUSTER_IMAGE_ID_TAG, PCLUSTER_VERSION_TAG

LOGGER = logging.getLogger(__name__)


class CfnClient(Boto3Client):
    """Implement CFN Boto3 client."""

    def __init__(self):
        super().__init__("cloudformation")

    @AWSExceptionHandler.handle_client_exception
    def create_stack(self, stack_name: str, disable_rollback: bool, tags: list, template_body: str):
        """Create CFN stack by using the given template."""
        return self._client.create_stack(
            StackName=stack_name,
            TemplateBody=template_body,
            Capabilities=["CAPABILITY_IAM"],
            DisableRollback=disable_rollback,
            Tags=tags,
        )

    @AWSExceptionHandler.handle_client_exception
    def create_stack_from_url(
        self,
        stack_name: str,
        disable_rollback: bool,
        tags: list,
        template_url: str,
        capabilities: str = "CAPABILITY_IAM",
    ):
        """Create CFN stack by using the given template url."""
        return self._client.create_stack(
            StackName=stack_name,
            TemplateURL=template_url,
            Capabilities=[capabilities],
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
    def update_stack_from_url(self, stack_name: str, template_url: str, tags: list = None):
        """Update CFN stack by using the given template url."""
        if tags is None:
            return self._client.update_stack(
                StackName=stack_name,
                TemplateURL=template_url,
                Capabilities=["CAPABILITY_IAM"],
            )
        return self._client.update_stack(
            StackName=stack_name,
            TemplateURL=template_url,
            Capabilities=["CAPABILITY_IAM"],
            Tags=tags,
        )

    @AWSExceptionHandler.handle_client_exception
    @AWSExceptionHandler.retry_on_boto3_throttling
    def describe_stack(self, stack_name: str):
        """Get information for the given stack."""
        try:
            return self._client.describe_stacks(StackName=stack_name).get("Stacks")[0]
        except ClientError as e:
            if e.response["Error"]["Code"] == AWSClientError.ErrorCode.VALIDATION_ERROR.value:
                LOGGER.info("Could not describe CloudFormation stack %s: %s", stack_name, e)
                raise StackNotFoundError(function_name="describe_stack", stack_name=stack_name)
            raise

    @AWSExceptionHandler.handle_client_exception
    @AWSExceptionHandler.retry_on_boto3_throttling
    def get_stack_events(self, stack_name, next_token=None):
        """Return the events of a stack, start from next_token if provided."""
        if next_token:
            return self._client.describe_stack_events(StackName=stack_name, NextToken=next_token)
        else:
            return self._client.describe_stack_events(StackName=stack_name)

    @staticmethod
    def format_event(event):
        """Format CFN Stack event."""
        return "{} {} {} {} {}".format(
            event.get("Timestamp").isoformat(timespec="seconds"),
            event.get("ResourceStatus"),
            event.get("ResourceType"),
            event.get("LogicalResourceId"),
            event.get("ResourceStatusReason", ""),
        )

    def stack_exists(self, stack_name: str):
        """Return a boolean describing whether or not a stack by the given name exists."""
        try:
            self.describe_stack(stack_name)
            return True
        except StackNotFoundError:
            return False

    @AWSExceptionHandler.handle_client_exception
    def get_stack_template(self, stack_name: str):
        """Get stack template."""
        return self._client.get_template(StackName=stack_name).get("TemplateBody")

    @AWSExceptionHandler.handle_client_exception
    def list_pcluster_stacks(self, next_token=None):
        """List existing pcluster cluster stacks."""
        stacks, result_token = self._list_parentless_stacks_with_tag(PCLUSTER_VERSION_TAG, next_token)
        # Only return stacks without image-id tag, which means they are cluster stacks.
        return [stack for stack in stacks if StackInfo(stack).get_tag(PCLUSTER_IMAGE_ID_TAG) is None], result_token

    def describe_stack_resource(self, stack_name: str, logic_resource_id: str):
        """Get stack resource information."""
        try:
            return self._client.describe_stack_resource(StackName=stack_name, LogicalResourceId=logic_resource_id)
        except Exception:
            raise AWSClientError(
                function_name="describe_stack_resource", message=f"No resource {logic_resource_id} found."
            )

    @AWSExceptionHandler.handle_client_exception
    def get_imagebuilder_stacks(self, next_token=None):
        """List existing imagebuilder stacks."""
        return self._list_parentless_stacks_with_tag(PCLUSTER_IMAGE_ID_TAG, next_token)

    def _list_parentless_stacks_with_tag(self, tag, next_token=None):
        describe_stacks_kwargs = {}
        if next_token:
            describe_stacks_kwargs["NextToken"] = next_token

        result = self._client.describe_stacks(**describe_stacks_kwargs)
        stack_list = []
        for stack in result.get("Stacks", []):
            if stack.get("ParentId") is None and StackInfo(stack).get_tag(tag):
                stack_list.append(stack)
        return stack_list, result.get("NextToken")
