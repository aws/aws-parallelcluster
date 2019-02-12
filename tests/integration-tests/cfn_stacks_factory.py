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

import boto3
from botocore.exceptions import ClientError
from retrying import retry

from utils import random_alphanumeric, retrieve_cfn_outputs


class CfnStack:
    """Identify a CloudFormation stack."""

    def __init__(self, name, region, template):
        self.name = name
        self.region = region
        self.template = template
        self.__cfn_outputs = None

    @property
    def cfn_outputs(self):
        """
        Return the CloudFormation stack outputs for the stack.
        Outputs are retrieved only once and then cached.
        """
        if self.__cfn_outputs:
            return self.__cfn_outputs
        self.__cfn_outputs = retrieve_cfn_outputs(self.name, self.region)
        return self.__cfn_outputs


class CfnStacksFactory:
    """Manage creation and deletion of CloudFormation stacks."""

    def __init__(self):
        self.__created_stacks = {}

    def create_stack(self, region, template, name=None):
        """
        Create a cfn stack with a given template.
        :param template: template to use for stack creation.
        :param name: name of the stack. If not specified it defaults to "integ-tests-" + random_alphanumeric()
        :return:
        """
        if not name:
            name = "integ-tests-" + random_alphanumeric()

        if self.__get_stack_internal_id(name, region) in self.__created_stacks:
            raise ValueError("Stack {0} already exists in region {1}".format(name, region))

        # create the cluster
        logging.info("Creating stack {0} in region {1}".format(name, region))
        id = self.__get_stack_internal_id(name, region)
        self.__created_stacks[id] = CfnStack(name, region, template)
        try:
            cfn_client = boto3.client("cloudformation", region_name=region)
            cfn_client.create_stack(StackName=name, TemplateBody=template)
            final_status = self.__wait_for_stack_creation(name, cfn_client)
            self.__assert_stack_status(final_status, "CREATE_COMPLETE")
        except Exception as e:
            logging.error("Creation of stack {0} in region {1} failed with exception: {2}".format(name, region, e))
            raise

        logging.info("Cluster {0} created successfully in region {1}".format(name, region))
        return self.__created_stacks[id]

    @retry(
        stop_max_attempt_number=10,
        wait_fixed=5000,
        retry_on_exception=lambda exception: isinstance(exception, ClientError),
    )
    def delete_stack(self, name, region):
        """Destroy a created cfn stack."""
        id = self.__get_stack_internal_id(name, region)
        if id in self.__created_stacks:
            logging.info("Destroying stack {0} in region {1}".format(name, region))
            try:
                stack = self.__created_stacks[id]
                cfn_client = boto3.client("cloudformation", region_name=stack.region)
                cfn_client.delete_stack(StackName=stack.name)
                final_status = self.__wait_for_stack_deletion(name, cfn_client)
                self.__assert_stack_status(final_status, "DELETE_COMPLETE")
            except Exception as e:
                logging.error("Deletion of stack {0} in region {1} failed with exception: {2}".format(name, region, e))
                raise
            del self.__created_stacks[id]
            logging.info("Cluster {0} deleted successfully in region {1}".format(name, region))
        else:
            logging.warning("Couldn't find cluster with name {0} in region. Skipping deletion.".format(name, region))

    def delete_all_stacks(self):
        """Destroy all created stacks."""
        logging.debug("Destroying all cfn stacks")
        for _, value in dict(self.__created_stacks).items():
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
        retry_on_exception=lambda e: False,
    )
    def __wait_for_stack_creation(self, name, cfn_client):
        return self.__get_stack_status(name, cfn_client)

    @retry(
        retry_on_result=lambda result: result == "DELETE_IN_PROGRESS",
        wait_fixed=5000,
        retry_on_exception=lambda e: False,
    )
    def __wait_for_stack_deletion(self, name, cfn_client):
        return self.__get_stack_status(name, cfn_client)

    @staticmethod
    def __get_stack_status(name, cfn_client):
        return cfn_client.describe_stacks(StackName=name).get("Stacks")[0].get("StackStatus")

    @staticmethod
    def __assert_stack_status(status, expected_status):
        if status != expected_status:
            raise Exception("Stack status {0} differs from expected one {1}".format(status, expected_status))

    @staticmethod
    def __get_stack_internal_id(name, region):
        return name + "-" + region
