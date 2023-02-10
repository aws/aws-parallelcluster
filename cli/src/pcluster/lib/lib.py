# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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


from typing import Callable, Dict

import yaml

import pcluster.api.controllers.cluster_operations_controller
import pcluster.api.errors
import pcluster.cli.model
from pcluster.cli.entrypoint import dispatch, param_coerce
from pcluster.utils import to_snake_case


# The definition of the shape of model is defined in pcluster.cli.model
def _gen_func_map(model: Dict) -> Dict[str, Callable]:
    """Generate a dict mapping function names to dispatch functions."""

    class Args:
        """An Args class with  structure to be used during dispatch."""

        def __init__(self, args):
            self.__dict__ = args

    # Much like the CLI, we add wait commands for these cluster options to
    # allow the user to have these be synchronous. This is done at the argument
    # parser level on the CLI side.
    wait_ops = ["create-cluster", "delete-cluster", "update-cluster"]
    for op_name in filter(lambda x: x in model, wait_ops):
        wait_param = {"body": False, "type": "boolean", "name": "wait", "required": False}
        model[op_name]["params"].append(wait_param)

    def make_func(op_name: str) -> Callable:
        """Take the name of an operation and return the function that call the controller."""

        def func(**kwargs):
            # Validate that args provided match the model
            params = model[op_name]["params"]
            expected = {to_snake_case(param["name"]) for param in params if param["required"]}
            missing = expected - set(kwargs.keys())
            if missing:
                raise TypeError(f"<{op_name}> missing required arguments: {missing}")

            all_args = {to_snake_case(param["name"]) for param in params}
            unexpected = set(kwargs.keys()) - all_args - {"query", "debug"}
            if unexpected:
                raise TypeError(f"<{op_name}> got unexpected arguments: {unexpected}")

            kwargs["func"] = None
            kwargs["operation"] = op_name
            for param in model[op_name]["params"]:
                param_name = to_snake_case(param["name"])
                if param_name not in kwargs:
                    kwargs[param_name] = None
                # Convert python data to strings for args of type "file"
                elif not isinstance(kwargs.get(param_name), str) and param["type"] == "file":
                    kwargs[param_name] = yaml.dump(kwargs[param_name])
                else:
                    kwargs[param_name] = param_coerce(param)(kwargs[param_name])

            return dispatch(model, Args(kwargs))

        return func

    return {to_snake_case(op): make_func(op) for op in model}


def _load_model():
    """Load the ParallelCluster model from the package spec."""
    spec = pcluster.cli.model.package_spec()
    return pcluster.cli.model.load_model(spec)


def _add_functions(model, obj):
    """Add parallel cluster functionality to the module."""
    for func_name, func in _gen_func_map(model).items():
        setattr(obj, func_name, func)
