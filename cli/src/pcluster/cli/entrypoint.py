#!/usr/bin/env python3
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
# pylint: disable=import-outside-toplevel

import argparse
from botocore.exceptions import NoCredentialsError  # TODO: remove
import base64
from functools import partial
import inspect
import json
import os
import re
import sys
import logging.config

from pcluster.api import encoder
import pcluster.api.errors
import pcluster.cli.commands.cluster as cluster_commands
import pcluster.cli.commands.image as image_commands
import pcluster.cli.logging as pcluster_logging
from pcluster.cli.middleware import middleware_hooks, add_additional_args
import pcluster.cli.model
from pcluster.cli.commands.common import CliCommand
from pcluster.utils import camelcase, to_snake_case, get_cli_log_file

# Controllers
import pcluster.api.controllers.cluster_compute_fleet_controller
import pcluster.api.controllers.cluster_instances_controller
import pcluster.api.controllers.cluster_operations_controller
import pcluster.api.controllers.image_operations_controller

LOGGER = logging.getLogger(__name__)


class APIOperationException(Exception):
    def __init__(self, data):
        self.data = data


class ParameterException(Exception):
    def __init__(self, data):
        self.data = data


def _exit_msg(msg):
    raise ParameterException({'message': msg})


def bool_converter(param, in_str):
    """Takes a boolean string and converts it into a boolean value."""
    if in_str in {'false', 'False', 'FALSE', False}:
        return False
    elif in_str in {'true', 'True', 'TRUE', True}:
        return True
    _exit_msg(f"Bad Request: Wrong type, expected 'boolean' for parameter '{param}'")


def re_validator(rexp_str, param, in_str):
    """Takes a string and validates the input format."""
    rexp = re.compile(rexp_str)
    if rexp.match(in_str) is None:
        _exit_msg(f"Bad Request: '{in_str}' does not match '{rexp_str}' - '{param}'")
    return in_str


def read_file_b64(param, path):
    """Takes file path, reads the file and converts to base64 encoded string"""
    try:
        with open(path) as file:
            file_data = file.read()
    except FileNotFoundError:
        _exit_msg(f"Bad Request: File not found: '{path}'")
    except UnicodeDecodeError:
        _exit_msg(f"Bad Request: Unicode error: Perhaps input file '{path}' is not yaml.")

    return base64.b64encode(file_data.encode('utf-8')).decode('utf-8')


def to_number(param, in_str):
    """Takes a string and converts it into a double."""
    try:
        return float(in_str)
    except ValueError:
        _exit_msg(f"Bad Request: Wrong type, expected 'number' for parameter '{param}'")


def to_int(param, in_str):
    """Takes a string and converts it into an int."""
    try:
        return int(in_str)
    except ValueError:
        _exit_msg(f"Bad Request: Wrong type, expected 'number' for parameter '{param}'")


def convert_args(model, op_name, args_in):
    """Takes a model, the name of the operation and the arguments
    provided by argparse and converts the parameters into a format
    that is suitable to be called in the controllers."""
    body = {}
    kwargs = {}
    for param in model[op_name]['params']:
        param_name = to_snake_case(param['name'])
        value = args_in.pop(param_name)

        if param['body']:
            param_name = camelcase(param_name)
            param_name = param_name[0].lower() + param_name[1:]
            body[param_name] = value
        else:
            kwargs[param_name] = value

    kwargs.update(args_in)
    body_name = model[op_name].get('body_name')
    if body_name:
        kwargs[body_name] = body

    return body, kwargs


def dispatch(model, args):
    """Dispatches to a controller function when the arguments have an
    operation specified."""
    args_dict = args.__dict__
    operation = args.operation
    del args_dict['func']
    del args_dict['operation']
    body, kwargs = convert_args(model, operation, args_dict)

    dispatch_func = partial(pcluster.cli.model.call, model[operation]['func'])

    # middleware provides an opportunity to customize the calling of the
    # underlying API function on a per-operation basis
    middleware = middleware_hooks()
    if operation in middleware:
        return middleware[operation](dispatch_func, body, kwargs)
    else:
        return dispatch_func(**kwargs)


def gen_parser(model):
    """Takes a model and returns an ArgumentParser for converting command line
    arguments into values based on that model."""
    desc = ("pcluster is the AWS ParallelCluster CLI and permits "
            "launching and management of HPC clusters in the AWS cloud.")
    epilog = 'For command specific flags, please run: "pcluster [command] --help"'
    parser = argparse.ArgumentParser(description=desc, epilog=epilog)
    subparsers = parser.add_subparsers(help="", title='COMMANDS', dest='operation')
    subparsers.required = True
    type_map = {'number': to_number, 'boolean': bool_converter, 'byte': read_file_b64}
    parser_map = {'subparser': subparsers}

    # Add each operation as it's onn parser with params / body as arguments
    for op_name, operation in model.items():
        op_help = operation.get('description', f"{op_name} command help")
        subparser = subparsers.add_parser(op_name, help=op_help, description=op_help)
        parser_map[op_name] = subparser

        for param in operation['params']:
            help = param.get('description', '')

            # handle regexp parameter validation (or perform type coercion)
            if 'pattern' in param:
                type_coerce = partial(re_validator, param['pattern'], param['name'])
            elif param.get('type') in type_map:
                type_coerce = partial(type_map[param['type']], param['name'])
            else:
                type_coerce = None

            # add teh parameter to the parser based on type from model / specification
            subparser.add_argument(f"--{param['name']}",
                                   required=param.get('required', False),
                                   choices=param.get('enum', None),
                                   nargs='+' if 'multi' in param else None,
                                   type=type_coerce,
                                   help=help)

        subparser.add_argument("--debug", action="store_true", help="Turn on debug logging.", default=False)
        subparser.set_defaults(func=partial(dispatch, model))

    return parser, parser_map


def add_cli_commands(parser_map):
    """Adds additional CLI arguments that don't belong to the API."""
    subparsers = parser_map['subparser']

    # add all non-api commands via introspection
    for _name, obj in inspect.getmembers(cluster_commands) + inspect.getmembers(image_commands):
        if (inspect.isclass(obj)
                and issubclass(obj, CliCommand)
                and not inspect.isabstract(obj)):
            obj(subparsers)

    add_additional_args(parser_map)


def run(sys_args, spec=None):
    spec = spec or pcluster.cli.model.package_spec()
    model = pcluster.cli.model.load_model(spec)
    parser, parser_map = gen_parser(model)
    add_cli_commands(parser_map)
    args, extra_args = parser.parse_known_args(sys_args)

    # some commands (e.g. ssh and those defined as CliCommand objects) require 'extra_args'
    if extra_args and (not hasattr(args, 'expects_extra_args') or not args.expects_extra_args):
        parser.print_usage()
        print("Invalid arguments %s" % extra_args)
        sys.exit(1)

    if args.debug:
        logging.getLogger("pcluster").setLevel(logging.DEBUG)

    # Remove the debug parameter from args since it should not persist to api
    # operations (the above setting should be sufficient.)
    if 'debug' in args.__dict__:
        del args.__dict__['debug']

    # TODO: remove this logic from here
    # set region in the environment to make it available to all the boto3 calls
    if "region" in args and args.region:
        os.environ["AWS_DEFAULT_REGION"] = args.region

    LOGGER.debug("Handling CLI command %s", args.operation)  # ToDo: change the level to info after finishing API.
    LOGGER.debug("Parsed CLI arguments: args(%s), extra_args(%s)", args, extra_args)

    # TODO: remove when ready to switch over to spec-based implementations
    v2_implemented = {'list-images', 'build-image', 'delete-image',
                      'describe-image', 'list-clusters'}
    if args.operation in model and args.operation not in v2_implemented:
        # TODO: remove once all commands are converted
        logging.getLogger("pcluster").removeHandler(logging.getLogger("pcluster").handlers[1])
        try:
            return args.func(args)
        except Exception as e:
            # format exception messages in the same manner as the api
            message = pcluster.api.errors.exception_message(e)
            error_encoded = encoder.JSONEncoder().encode(message)
            raise APIOperationException(json.loads(error_encoded))
    else:
        return args.func(args, extra_args)


def main():
    pcluster_logging.config_logger()
    try:
        ret = run(sys.argv[1:])
        if ret:
            print(json.dumps(ret, indent=2))
        sys.exit(0)
    except NoCredentialsError:  # TODO: remove from here
        LOGGER.error("AWS Credentials not found.")
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.debug("Received KeyboardInterrupt. Exiting.")
        sys.exit(1)
    except ParameterException as e:
        print(json.dumps(e.data, indent=2))
        sys.exit(1)
    except APIOperationException as e:
        import traceback
        with open(get_cli_log_file(), 'a+') as outfile:
            traceback.print_exc(file=outfile)
        print(json.dumps(e.data, indent=2))
        sys.exit(1)
    except Exception as e:
        LOGGER.exception("Unexpected error of type %s: %s", type(e).__name__, e)
        sys.exit(1)


if __name__ == "__main__":
    main()
