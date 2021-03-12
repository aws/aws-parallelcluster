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


class StackInfo:
    """Object to store Stack information, initialized with a describe_stacks call."""

    def __init__(self, stack_data: dict):
        """
        Init StackInfo by performing a describe_stacks call.

        If the stack doesn't exist it raises an exception.
        """
        self._stack_data = stack_data
        self._params = self._stack_data.get("Parameters", [])
        self._tags = self._stack_data.get("Tags", [])
        self.outputs = self._stack_data.get("Outputs", [])

    @property
    def id(self):
        """Return the id/arn of the stack."""
        return self._stack_data.get("StackId")

    @property
    def name(self):
        """Return the name of the stack."""
        return self._stack_data.get("StackName")

    @property
    def status(self):
        """Return the status of the stack."""
        return self._stack_data.get("StackStatus")

    @property
    def is_working_status(self):
        """Return true if the stack is in a working status."""
        return self.status in ["CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"]

    def _get_tag(self, tag_key: str):
        return next(iter([tag["Value"] for tag in self._tags if tag["Key"] == tag_key]), None)

    def _get_output(self, output_key: str):
        return next((out["OutputValue"] for out in self.outputs if out["OutputKey"] == output_key), None)

    def _get_param(self, key_name):
        """
        Get parameter value from Cloudformation Stack Parameters.

        :param key_name: Parameter Key
        :return: ParameterValue if that parameter exists, otherwise None
        """
        param_value = next((par["ParameterValue"] for par in self._params if par["ParameterKey"] == key_name), None)
        return param_value.strip()


class InstanceInfo:
    """Object to store Instance information, initialized with a describe_instances call."""

    def __init__(self, instance_data: dict):
        self._instance_data = instance_data

    @property
    def id(self) -> str:
        """Return instance id."""
        return self._instance_data.get("InstanceId")

    @property
    def state(self) -> str:
        """Return instance state."""
        return self._instance_data.get("State").get("Name")

    @property
    def public_ip(self) -> str:
        """Return Public Ip of the instance or None if not present."""
        return self._instance_data.get("PublicIpAddress", None)

    @property
    def private_ip(self) -> str:
        """Return Private Ip of the instance."""
        return self._instance_data.get("PrivateIpAddress")
