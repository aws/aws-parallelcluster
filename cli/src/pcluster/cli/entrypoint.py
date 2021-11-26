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

import inspect
import json
import logging.config
import os
import re
import sys
from functools import partial

import argparse
from botocore.exceptions import NoCredentialsError  # TODO: remove

# Controllers
import pcluster.api.controllers.cluster_compute_fleet_controller
import pcluster.api.controllers.cluster_instances_controller
import pcluster.api.controllers.cluster_operations_controller
import pcluster.api.controllers.image_operations_controller
import pcluster.api.errors
import pcluster.cli.commands.commands as cli_commands
import pcluster.cli.logger as pcluster_logging
import pcluster.cli.model
from pcluster.api import encoder
from pcluster.cli.commands.common import CliCommand, exit_msg, to_bool, to_int, to_number
from pcluster.cli.exceptions import APIOperationException, ParameterException
from pcluster.cli.logger import redirect_stdouterr_to_logger
from pcluster.cli.middleware import add_additional_args, middleware_hooks
from pcluster.utils import to_camel_case, to_snake_case

LOGGER = logging.getLogger(__name__)


def re_validator(rexp_str, param, in_str):
    """Take a string and validate the input format."""
    rexp = re.compile(rexp_str)
    if rexp.match(in_str) is None:
        exit_msg(f"Bad Request: '{in_str}' does not match '{rexp_str}' - '{param}'")
    return in_str


def read_file(_param, path):
    """Take file path, read the file and return the data as a string."""
    try:
        with open(path, encoding="utf-8") as file:
            file_data = file.read()
    except FileNotFoundError:
        exit_msg(f"Bad Request: File not found: '{path}'")
    return file_data


def convert_args(model, op_name, args_in):
    """Convert the model into body and args suitable for calling.

    Takes a model, the name of the operation and the arguments
    provided by argparse and converts the parameters into a format
    that is suitable to be called in the controllers.
    """
    body = {}
    kwargs = {}
    for param in model[op_name]["params"]:
        param_name = to_snake_case(param["name"])
        value = args_in.pop(param_name)

        if param["body"]:
            param_name = to_camel_case(param_name)
            body[param_name] = value
        else:
            kwargs[param_name] = value

    kwargs.update(args_in)
    body_name = model[op_name].get("body_name")
    if body_name:
        kwargs[body_name] = body

    return body, kwargs


def dispatch(model, args):
    """Dispatch to a controller function or middleware with args."""
    args_dict = args.__dict__
    operation = args.operation
    del args_dict["func"]
    del args_dict["operation"]
    body, kwargs = convert_args(model, operation, args_dict)

    dispatch_func = partial(pcluster.cli.model.call, model[operation]["func"])

    # middleware provides an opportunity to customize the calling of the
    # underlying API function on a per-operation basis
    middleware = middleware_hooks()
    if operation in middleware:
        return middleware[operation](dispatch_func, body, kwargs)
    else:
        return dispatch_func(**kwargs)


def gen_parser(model):
    """Take a model and returns an ArgumentParser for CLI parsing."""
    desc = (
        "pcluster is the AWS ParallelCluster CLI and permits "
        "launching and management of HPC clusters in the AWS cloud."
    )
    epilog = 'For command specific flags, please run: "pcluster [command] --help"'
    parser = argparse.ArgumentParser(description=desc, epilog=epilog)
    subparsers = parser.add_subparsers(help="", title="COMMANDS", dest="operation")
    subparsers.required = True
    type_map = {"number": to_number, "boolean": to_bool, "integer": to_int, "file": read_file}
    parser_map = {"subparser": subparsers}

    # Add each operation as it's onn parser with params / body as arguments
    for op_name, operation in model.items():
        op_help = operation.get("description", f"{op_name} command help")
        subparser = subparsers.add_parser(op_name, help=op_help, description=op_help)
        parser_map[op_name] = subparser

        for param in operation["params"]:
            help = param.get("description", "")

            # handle regexp parameter validation (or perform type coercion)
            if "pattern" in param:
                type_coerce = partial(re_validator, param["pattern"], param["name"])
            elif param.get("type") in type_map:
                type_coerce = partial(type_map[param["type"]], param["name"])
            else:
                type_coerce = None

            abbrev_args = {
                "cluster-name": "-n",
                "image-id": "-i",
                "region": "-r",
                "cluster-configuration": "-c",
                "image-configuration": "-c",
            }
            if param["name"] in abbrev_args:
                arg_name = [abbrev_args[param["name"]], f"--{param['name']}"]
            else:
                arg_name = [f"--{param['name']}"]

            # add the parameter to the parser based on type from model / specification
            subparser.add_argument(
                *arg_name,
                required=param.get("required", False),
                choices=param.get("enum", None),
                nargs="+" if "multi" in param else None,
                type=type_coerce,
                help=help,
            )

        subparser.add_argument("--debug", action="store_true", help="Turn on debug logging.", default=False)
        subparser.add_argument("--query", help="JMESPath query to perform on output.")
        subparser.set_defaults(func=partial(dispatch, model))

    return parser, parser_map


def add_cli_commands(parser_map):
    """Add additional CLI arguments that don't belong to the API."""
    subparsers = parser_map["subparser"]

    # add all non-api commands via introspection
    for _name, obj in inspect.getmembers(cli_commands):
        if inspect.isclass(obj) and issubclass(obj, CliCommand) and not inspect.isabstract(obj):
            obj(subparsers)

    add_additional_args(parser_map)


def _run_operation(model, args, extra_args):
    if args.operation in model:
        try:
            with redirect_stdouterr_to_logger():
                return args.func(args)
        except KeyboardInterrupt as e:
            raise e
        except APIOperationException as e:
            raise e
        except ParameterException as e:
            raise e
        except Exception as e:
            # format exception messages in the same manner as the api
            message = pcluster.api.errors.exception_message(e)
            error_encoded = encoder.JSONEncoder().encode(message)
            raise APIOperationException(json.loads(error_encoded))
    else:
        return args.func(args, extra_args)


def run(sys_args, model=None):
    spec = pcluster.cli.model.package_spec()
    model = model or pcluster.cli.model.load_model(spec)
    parser, parser_map = gen_parser(model)
    add_cli_commands(parser_map)
    args, extra_args = parser.parse_known_args(sys_args)

    # some commands (e.g. ssh and those defined as CliCommand objects) require 'extra_args'
    if extra_args and (not hasattr(args, "expects_extra_args") or not args.expects_extra_args):
        parser.print_usage()
        print(f"Invalid arguments {extra_args}")
        sys.exit(1)

    if args.debug:
        logging.getLogger("pcluster").setLevel(logging.DEBUG)

    # Remove the debug parameter from args since it should not persist to api
    # operations (the above setting should be sufficient.)
    if "debug" in args.__dict__:
        del args.__dict__["debug"]

    # TODO: remove this logic from here
    # set region in the environment to make it available to all the boto3 calls
    if "region" in args and args.region:
        os.environ["AWS_DEFAULT_REGION"] = args.region

    LOGGER.info("Handling CLI command %s", args.operation)
    LOGGER.info("Parsed CLI arguments: args(%s), extra_args(%s)", args, extra_args)
    return _run_operation(model, args, extra_args)


def main():
    pcluster_logging.config_logger()
    try:
        ret = run(sys.argv[1:])
        if ret:
            output_str = json.dumps(ret, indent=2)
            print(output_str)
            LOGGER.info(output_str)
        sys.exit(0)
    except NoCredentialsError:  # TODO: remove from here
        LOGGER.error("AWS Credentials not found.")
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("Received KeyboardInterrupt. Exiting.")
        sys.exit(1)
    except ParameterException as e:
        print(json.dumps(e.data, indent=2))
        sys.exit(1)
    except APIOperationException as e:
        LOGGER.error(json.dumps(e.data), exc_info=True)
        print(json.dumps(e.data, indent=2))
        sys.exit(1)
    except BrokenPipeError:
        pass
    except Exception as e:
        LOGGER.exception("Unexpected error of type %s: %s", type(e).__name__, e)
        sys.exit(1)
    finally:
        # If an external process has closed the other end of this pipe, flush
        # now to see if we'd get a BrokenPipeError on exit and if so, dup2 a
        # devnull over that output.
        try:
            sys.stdout.flush()
        except BrokenPipeError:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())

        try:
            sys.stderr.flush()
        except BrokenPipeError:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stderr.fileno())


if __name__ == "__main__":
    LOGGER = logging.getLogger("pcluster")
    main()
