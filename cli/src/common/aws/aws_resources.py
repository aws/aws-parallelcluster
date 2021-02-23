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
from common.aws.aws_api import AWSApi
from common.boto3.common import AWSClientError
from pcluster.utils import get_region


class StackActionError(Exception):
    """Represent an error during the execution of an action on the stack."""

    def __init__(self, message: str):
        super().__init__(message)


class Stack:
    """Object to interact with a Stack, initialized with a describe_stacks call."""

    def __init__(self, stack_name: str):
        """
        Init StackInfo by performing a describe_stacks call.

        If the stack doesn't exist it raises an exception.
        """
        self.name = stack_name
        self.region = get_region()
        try:
            self._stack_data = AWSApi().instance().cfn.describe_stack(stack_name)
        except AWSClientError as e:
            if "does not exist" in str(e):
                raise StackActionError(f"The stack {stack_name} does not exist.")
            raise e
        self._params = self._stack_data.get("Parameters", [])
        self._tags = self._stack_data.get("Tags", [])
        self.outputs = self._stack_data.get("Outputs", [])

    @property
    def id(self):
        """Return the id/arn of the stack."""
        return self._stack_data.get("StackId")

    @property
    def status(self):
        """Return the status of the stack."""
        return self._stack_data.get("StackStatus")

    @property
    def template(self):
        """Return the template body of the stack."""
        return self._stack_data.get("TemplateBody")

    def _get_tag(self, tag_key: str):
        return next(iter([tag["Value"] for tag in self._tags if tag["Key"] == tag_key]), None)

    def _get_output(self, output_key: str):
        return next((o.get("OutputValue") for o in self.outputs if o.get("OutputKey") == output_key), None)

    def updated_status(self):
        """Return updated status."""
        return AWSApi().instance().cfn.describe_stack(self.name).get("StackStatus")

    def delete(self):
        """Delete stack."""
        try:
            # delete_stack does not raise an exception if stack does not exist
            # Use describe_stacks to explicitly check if the stack exists
            AWSApi().instance().cfn.delete_stack(self.name)

            # if self.updated_status() == "DELETE_FAILED":
            #    raise StackActionError(f"Cluster {self.name} did not delete successfully.")

        except Exception as e:
            raise StackActionError(f"Cluster {self.name} did not delete successfully. {e}")
