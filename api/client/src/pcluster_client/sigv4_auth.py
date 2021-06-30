"""Sigv4 Signing Support"""
# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy
# of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS
# OF ANY KIND, express or implied. See the License for the specific
# language governing permissions and limitations under the License.

import boto3
import botocore
import json


def sigv4_auth(method, host, path, querys, body, headers):
    "Adds authorization headers for sigv4 to headers parameter."
    endpoint = host.replace('https://', '').replace('http://', '')
    _api_id, _service, region, _domain = endpoint.split('.', maxsplit=3)

    request_parameters = '&'.join([f"{k}={v}" for k, v in querys])
    url = f"{host}{path}?{request_parameters}"

    session = botocore.session.Session()
    data = json.dumps(body) if body else None
    request = botocore.awsrequest.AWSRequest(method=method,
                                             url=url,
                                             data=data)
    botocore.auth.SigV4Auth(session.get_credentials(),
                            "execute-api", region).add_auth(request)
    prepared_request = request.prepare()

    headers['host'] = endpoint.split('/', maxsplit=1)[0]
    for k, value in prepared_request.headers.items():
        headers[k] = value
