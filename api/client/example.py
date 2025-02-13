#!/usr/bin/env python3
# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy
# of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, express or implied. See the License for the specific
# language governing permissions and limitations under the License.

import boto3
import click
from pcluster_client.api import cluster_operations_api
from pcluster_client import Configuration, ApiClient, ApiException


@click.command()
@click.option("--stack-name", help="ParallelCluster API stack name")
@click.option("--region", help="AWS region")
def request(stack_name: str, region: str):
    """Makes a simple request to the API Gateway"""
    invoke_url = describe_stack_output(region, stack_name, "ParallelClusterApiInvokeUrl")
    configuration = Configuration(host=invoke_url)

    with ApiClient(configuration) as api_client:
        client = cluster_operations_api.ClusterOperationsApi(api_client)
        region_filter = region

        try:
            response = client.list_clusters(region=region_filter)
            print("Response: ", response)
        except ApiException as ex:
            print("Exception when calling ClusterOperationsApi->list_clusters: %s\n" % ex)


def describe_stack_output(region: str, stack_name: str, output_name: str):
    try:
        # Describe stack
        cloudformation = boto3.client("cloudformation", region_name=region)
        response = cloudformation.describe_stacks(StackName=stack_name)

        # Get the stack details
        stacks = response.get("Stacks", [])
        if not stacks:
            print(f"No stacks found with the name: {stack_name}")
            return None

        # Extract output
        outputs = stacks[0].get("Outputs", [])
        return list(filter(lambda o: o['OutputKey'] == 'ParallelClusterApiInvokeUrl', outputs))[0]['OutputValue']

    except Exception as e:
        print(f"Cannot describe output '{output_name}' for stack '{stack_name}': {e}")
        return None

if __name__ == "__main__":
    request()
