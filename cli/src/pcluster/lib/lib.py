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


import json
import logging.config
from functools import partial

import yaml

import pcluster.api.controllers.cluster_operations_controller
import pcluster.api.errors
import pcluster.cli.logger as pcluster_logging
import pcluster.cli.model
from pcluster.api import encoder
from pcluster.cli.entrypoint import dispatch, param_coerce
from pcluster.cli.exceptions import APIOperationException, ParameterException
from pcluster.cli.logger import redirect_stdouterr_to_logger
from pcluster.utils import to_snake_case


def _gen_class(model):
    """A function that accepts a model in the shape of the CLI model
    to generate a dictionary mapping function names to dispatch functions."""

    class Args():
        """An Args class that has the appropriate structure to be used during
        dispatch, which effectively just has a __dict__ in it."""
        def __init__(self, args):
            self.__dict__ = args

    def make_func(op_name):
        """Takes the name of an operation and generates the function that will
        call the underlying controler ensuring that default arguments are
        provided and that arguments are coerced."""
        def func(_self, **kwargs):

            # Validate that the input args match the model as this is normally done either
            # in the api or in the arg parsing in the CLI
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
                # Convert python data-structures into strings for those args
                # which are of type "file"
                elif not isinstance(kwargs.get(param_name), str) and param['type'] == 'file':
                    kwargs[param_name] = yaml.dump(kwargs[param_name])
                else:
                    kwargs[param_name] = param_coerce(param)(kwargs[param_name])

            return dispatch(model, Args(kwargs))

        return func

    return {to_snake_case(op): make_func(op) for op in model}


def _load_model():
    """Loads the ParallelCluster model from the package spec."""
    spec = pcluster.cli.model.package_spec()
    return pcluster.cli.model.load_model(spec)


def _make_class(model):
    """Creates a python class from a provided model."""
    return type("ParallelCluster", (object, ), _gen_class(model))


ParallelCluster = _make_class(_load_model())
