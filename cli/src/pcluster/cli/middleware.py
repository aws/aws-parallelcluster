# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not
# use this file except in compliance with the License. A copy of the License is
# located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or
# implied. See the License for the specific language governing permissions and
# limitations under the License.
"""
This module defines middleware functions for command line operations.

This allows the ability to provide custom logic either before or after running
an operation by specifying the name of the operation, and then calling the
function that is provided as the first argument and passing the **kwargs
provided.
"""

import argparse
import boto3

import pcluster.cli.model


def _cluster_status(cluster_name):
    controller = "cluster_operations_controller"
    func_name = "describe_cluster"
    full_func_name = f"pcluster.api.controllers.{controller}.{func_name}"
    return pcluster.cli.model.call(full_func_name, cluster_name=cluster_name)


def add_additional_args(parser_map):
    """Add any additional arguments to parsers for individual operations.

    NOTE: these additional arguments will also need to be removed before
    calling the underlying function for the situation where they are not a part
    of the specification.
    """
    parser_map["create-cluster"].add_argument("--wait", action="store_true", help=argparse.SUPPRESS)
    parser_map["delete-cluster"].add_argument("--wait", action="store_true", help=argparse.SUPPRESS)


def middleware_hooks():
    """Return a map and from operation to middleware functions.

    The map has operation names as the keys and functions as values.
    """
    return {"create-cluster": create_cluster, "delete-cluster": delete_cluster}


def create_cluster(func, body, kwargs):
    wait = kwargs.pop("wait", False)
    ret = func(**kwargs)
    if wait:
        cloud_formation = boto3.client("cloudformation")
        waiter = cloud_formation.get_waiter("stack_create_complete")
        waiter.wait(StackName=body["name"])
        ret = _cluster_status(body["name"])
    return ret


def delete_cluster(func, _body, kwargs):
    wait = kwargs.pop("wait", False)
    ret = func(**kwargs)
    if wait:
        cloud_formation = boto3.client("cloudformation")
        waiter = cloud_formation.get_waiter("stack_delete_complete")
        waiter.wait(StackName=kwargs["cluster_name"])
        return {"message": f"Successfully deleted cluster '{kwargs['cluster_name']}'."}
    else:
        return ret
