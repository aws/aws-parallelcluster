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
from pcluster.api.client.api import cluster_operations_api
from pcluster.api.client import Configuration, ApiClient, ApiException

apigateway = boto3.client('apigateway')


def request():
    """Makes a simple request to the API Gateway"""
    apis = apigateway.get_rest_apis()['items']
    api_id = next(api['id'] for api in apis if api['name'] == 'ParallelCluster')
    region = boto3.session.Session().region_name
    host = f"{api_id}.execute-api.{region}.amazonaws.com"
    configuration = Configuration(host=f"https://{host}/prod")

    with ApiClient(configuration) as api_client:
        client = cluster_operations_api.ClusterOperationsApi(api_client)
        region_filter = region

        try:
            response = client.list_clusters(region=region_filter)
            print("clusters: ", [c['cluster_name'] for c in response['items']])
        except ApiException as ex:
            print("Exception when calling ClusterOperationsApi->list_clusters: %s\n" % ex)


if __name__ == "__main__":
    request()
