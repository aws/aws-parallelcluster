# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import logging
import random
from collections import OrderedDict

import boto3
from assertpy import assert_that
from botocore.exceptions import ClientError
from framework.credential_providers import aws_credential_provider
from retrying import retry
from utils import (
    StackError,
    StackSetupError,
    get_cfn_events,
    retrieve_cfn_outputs,
    retrieve_cfn_resources,
    retrieve_tags,
    to_pascal_from_kebab_case,
)


class CfnStack:
    """Identify a CloudFormation stack."""

    def __init__(self, name, region, template, parameters=None, capabilities=None, tags=None):
        self.name = name
        self.region = region
        self.template = template
        self.parameters = parameters or []
        self.capabilities = capabilities or []
        self.tags = tags or []
        self.cfn_stack_id = None
        self.__cfn_outputs = None
        self.__cfn_resources = None

    def init_stack_data(self):
        """Initialize cfn_outputs and cfn_resources."""
        self.__cfn_outputs = retrieve_cfn_outputs(self.name, self.region)
        self.__cfn_resources = retrieve_cfn_resources(self.name, self.region)
        self.tags = retrieve_tags(self.name, self.region)

    @property
    def cfn_outputs(self):
        """
        Return the CloudFormation stack outputs for the stack.
        Outputs are retrieved only once and then cached.
        """
        if not self.__cfn_outputs:
            self.__cfn_outputs = retrieve_cfn_outputs(self.name, self.region)
        return self.__cfn_outputs

    @property
    def cfn_resources(self):
        """
        Return the CloudFormation stack resources for the stack.
        Resources are retrieved only once and then cached.
        """
        if not self.__cfn_resources:
            self.__cfn_resources = retrieve_cfn_resources(self.name, self.region)
        return self.__cfn_resources


class CfnVpcStack(CfnStack):
    """Identify a CloudFormation VPC stack."""

    # TODO add method to get N subnets
    def __init__(self, default_az_id: str = None, az_ids: list = None, **kwargs):
        super().__init__(**kwargs)
        self.default_az_id = default_az_id
        self.az_ids = az_ids
        self.az_override = None
        self.__public_subnet_ids = None
        self.__private_subnet_ids = None
        if "CAPABILITY_NAMED_IAM" not in self.capabilities:
            self.capabilities.append("CAPABILITY_NAMED_IAM")

    def set_az_override(self, az_override):
        """Sets the az_id to override the default AZ used to pick the subnets."""
        self.az_override = az_override

    def get_public_subnet(self):
        """Return the public subnet for a VPC stack."""
        return self._get_subnet(visibility="Public")

    def get_all_public_subnets(self):
        """Return all the public subnets for a VPC stack."""
        if not self.__public_subnet_ids:
            self.__public_subnet_ids, self.__private_subnet_ids = self._get_all_subnets()

        return self.__public_subnet_ids

    def get_private_subnet(self):
        """Return the private subnet for a VPC stack."""
        return self._get_subnet(visibility="Private")

    def get_all_private_subnets(self):
        """Return all the private subnets for a VPC stack."""
        if not self.__private_subnet_ids:
            self.__public_subnet_ids, self.__private_subnet_ids = self._get_all_subnets()

        return self.__private_subnet_ids

    def _get_subnet(self, visibility: str = "Public"):
        if self.az_override is not None:
            az_id_tag = to_pascal_from_kebab_case(self.az_override)
        elif self.default_az_id:
            az_id_tag = to_pascal_from_kebab_case(self.default_az_id)
        else:
            # get random subnet, if default is not set
            assert_that(self.az_ids).is_not_none()
            az_id_tag = to_pascal_from_kebab_case(random.choice(self.az_ids))

        assert_that(az_id_tag).is_not_none()
        return self.cfn_outputs[f"{az_id_tag}{visibility}SubnetId"]

    def _get_all_subnets(self):
        assert_that(self.az_ids).is_not_none()
        public_subnet_ids = []
        private_subnet_ids = []
        for az_id in self.az_ids:
            az_id_tag = to_pascal_from_kebab_case(az_id)
            public_subnet_ids.append(self.cfn_outputs[f"{az_id_tag}PublicSubnetId"])
            private_subnet_ids.append(self.cfn_outputs[f"{az_id_tag}PrivateSubnetId"])

        # shuffle the two subnets list in unison
        temp_subnets = list(zip(public_subnet_ids, private_subnet_ids))
        random.shuffle(temp_subnets)
        public_subnet_ids, private_subnet_ids = zip(*temp_subnets)

        logging.info(
            f"Setting public subnets list to {public_subnet_ids} and private subnets list to {private_subnet_ids}"
        )
        return list(public_subnet_ids), list(private_subnet_ids)


class CfnStacksFactory:
    """Manage creation and deletion of CloudFormation stacks."""

    def __init__(self, credentials):
        self.__created_stacks = OrderedDict()
        self.__credentials = credentials

    def create_stack(self, stack, stack_is_under_test=False):
        """
        Create a cfn stack with a given template.

        :param stack: stack to create.
        :param stack_is_under_test: indicates whether the creation of the stack is being tested or not.
        """
        name = stack.name
        region = stack.region

        id = self.__get_stack_internal_id(name, region)
        if id in self.__created_stacks:
            raise ValueError("Stack {0} already exists in region {1}".format(name, region))

        logging.info("Creating stack {0} in region {1}".format(name, region))
        is_template_url = stack.template.startswith("https://")
        with aws_credential_provider(region, self.__credentials):
            try:
                cfn_client = boto3.client("cloudformation", region_name=region)
                if is_template_url:
                    result = cfn_client.create_stack(
                        StackName=name,
                        TemplateURL=stack.template,
                        Parameters=stack.parameters,
                        Capabilities=stack.capabilities,
                        Tags=stack.tags,
                    )
                else:
                    result = cfn_client.create_stack(
                        StackName=name,
                        TemplateBody=stack.template,
                        Parameters=stack.parameters,
                        Capabilities=stack.capabilities,
                        Tags=stack.tags,
                    )
                stack.cfn_stack_id = result["StackId"]
                self.__created_stacks[id] = stack
                final_status = self.__wait_for_stack_creation(stack.cfn_stack_id, cfn_client)
                self.__assert_stack_status(
                    final_status,
                    "CREATE_COMPLETE",
                    region=region,
                    stack_name=stack.cfn_stack_id,
                    stack_is_under_test=stack_is_under_test,
                )
                # Initialize the stack data while still in the credential context
                stack.init_stack_data()
            except Exception as e:
                logging.error("Creation of stack {0} in region {1} failed with exception: {2}".format(name, region, e))
                raise

        logging.info("Stack {0} created successfully in region {1}".format(name, region))

    @retry(
        stop_max_attempt_number=10,
        wait_fixed=5000,
        retry_on_exception=lambda exception: isinstance(exception, ClientError),
    )
    def delete_stack(self, name, region):
        """Destroy a created cfn stack."""
        with aws_credential_provider(region, self.__credentials):
            internal_id = self.__get_stack_internal_id(name, region)
            if internal_id in self.__created_stacks:
                logging.info("Destroying stack {0} in region {1}".format(name, region))
                try:
                    stack = self.__created_stacks[internal_id]
                    cfn_client = boto3.client("cloudformation", region_name=stack.region)
                    cfn_client.delete_stack(StackName=stack.name)
                    final_status = self.__wait_for_stack_deletion(stack.cfn_stack_id, cfn_client)
                    self.__assert_stack_status(
                        final_status, "DELETE_COMPLETE", stack_name=stack.cfn_stack_id, region=region
                    )
                except Exception as e:
                    logging.error(
                        "Deletion of stack {0} in region {1} failed with exception: {2}".format(name, region, e)
                    )
                    raise
                del self.__created_stacks[internal_id]
                logging.info("Stack {0} deleted successfully in region {1}".format(name, region))
            else:
                logging.warning(
                    "Couldn't find stack with name {0} in region {1}. Skipping deletion.".format(name, region)
                )

    @retry(
        stop_max_attempt_number=10,
        wait_fixed=5000,
        retry_on_exception=lambda exception: isinstance(exception, ClientError),
    )
    def update_stack(
        self,
        name,
        region,
        parameters,
        stack_is_under_test=False,
        tags=None,
        template_body=None,
        wait_for_rollback=False,
    ):
        """Update a created cfn stack."""
        with aws_credential_provider(region, self.__credentials):
            internal_id = self.__get_stack_internal_id(name, region)
            if internal_id in self.__created_stacks:
                logging.info("Updating stack {0} in region {1}".format(name, region))
                try:
                    stack = self.__created_stacks[internal_id]
                    cfn_client = boto3.client("cloudformation", region_name=stack.region)
                    template_args = {"TemplateBody": template_body} if template_body else {"UsePreviousTemplate": True}
                    if tags is not None:
                        cfn_client.update_stack(StackName=stack.name, Parameters=parameters, Tags=tags, **template_args)
                    else:
                        cfn_client.update_stack(StackName=stack.name, Parameters=parameters, **template_args)

                    if wait_for_rollback:
                        final_status = self.__wait_for_stack_update_rollback(stack.cfn_stack_id, cfn_client)
                        self.__assert_stack_status(
                            final_status,
                            {"UPDATE_ROLLBACK_COMPLETE", "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS"},
                            stack_name=stack.cfn_stack_id,
                            region=region,
                            stack_is_under_test=stack_is_under_test,
                        )
                        stack.init_stack_data()
                    final_status = self.__wait_for_stack_update(stack.cfn_stack_id, cfn_client)
                    self.__assert_stack_status(
                        final_status,
                        {"UPDATE_COMPLETE", "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS"},
                        stack_name=stack.cfn_stack_id,
                        region=region,
                        stack_is_under_test=stack_is_under_test,
                    )

                    # Update the stack data while still in the credential context
                    stack.init_stack_data()
                except Exception as e:
                    logging.error(
                        "Update of stack {0} in region {1} failed with exception: {2}".format(name, region, e)
                    )
                    raise
                logging.info("Stack {0} updated successfully in region {1}".format(name, region))
            else:
                logging.warning(
                    "Couldn't find stack with name {0} in region {1}. Skipping update.".format(name, region)
                )

    def delete_all_stacks(self):
        """Destroy all created stacks."""
        logging.debug("Destroying all cfn stacks")
        for value in reversed(OrderedDict(self.__created_stacks).values()):
            try:
                self.delete_stack(value.name, value.region)
            except Exception as e:
                logging.error(
                    "Failed when destroying stack {0} in region {1} with exception {2}.".format(
                        value.name, value.region, e
                    )
                )

    @retry(
        retry_on_result=lambda result: result == "CREATE_IN_PROGRESS",
        wait_fixed=5000,
        retry_on_exception=lambda exception: isinstance(exception, ClientError) and "Rate exceeded" in str(exception),
    )
    def __wait_for_stack_creation(self, name, cfn_client):
        return self.__get_stack_status(name, cfn_client)

    @retry(
        retry_on_result=lambda result: result == "DELETE_IN_PROGRESS",
        wait_fixed=5000,
        retry_on_exception=lambda exception: isinstance(exception, ClientError) and "Rate exceeded" in str(exception),
    )
    def __wait_for_stack_deletion(self, name, cfn_client):
        return self.__get_stack_status(name, cfn_client)

    @retry(
        retry_on_result=lambda result: result == "UPDATE_IN_PROGRESS",
        wait_fixed=5000,
        retry_on_exception=lambda exception: isinstance(exception, ClientError) and "Rate exceeded" in str(exception),
    )
    def __wait_for_stack_update(self, name, cfn_client):
        return self.__get_stack_status(name, cfn_client)

    @retry(
        stop_max_attempt_number=30,
        retry_on_result=lambda result: result == "UPDATE_ROLLBACK_IN_PROGRESS"
        or result == "UPDATE_IN_PROGRESS"
        or result == "UPDATE_FAILED",
        wait_fixed=10000,
        retry_on_exception=lambda exception: isinstance(exception, ClientError) and "Rate exceeded" in str(exception),
    )
    def __wait_for_stack_update_rollback(self, name, cfn_client):
        return self.__get_stack_status(name, cfn_client)

    @staticmethod
    def __get_stack_status(name, cfn_client):
        return cfn_client.describe_stacks(StackName=name).get("Stacks")[0].get("StackStatus")

    @staticmethod
    def __assert_stack_status(status, expected_status, region, stack_name=None, stack_is_under_test=False):
        expected_status = {expected_status} if not isinstance(expected_status, set) else expected_status
        if status not in expected_status:
            message = (
                f"Stack status {status} for {stack_name} differs "
                f"from the expected status of {expected_status} in region {region}"
            )
            stack_events = get_cfn_events(stack_name, region=region)
            if stack_is_under_test:
                raise StackError(message, stack_events=stack_events)
            else:
                raise StackSetupError(message, stack_events=stack_events)

    @staticmethod
    def __get_stack_internal_id(name, region):
        return name + "-" + region
