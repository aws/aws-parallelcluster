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

import argparse
import base64
from functools import partial
import inspect
import re
import time
import sys
import yaml
from pprint import pprint

# For importing package resources
try:
    import importlib.resources as pkg_resources
except ImportError:
    import importlib_resources as pkg_resources

from connexion.utils import get_function_from_name
from pcluster.utils import camelcase
import pcluster.cli.commands.cluster as cluster_commands
from pcluster.cli.entrypoint import VersionCommand
from pcluster.api import openapi
from pcluster.cli.commands.common import CliCommand

# Controllers
import pcluster.api.controllers.cluster_compute_fleet_controller
import pcluster.api.controllers.cluster_instances_controller
import pcluster.api.controllers.cluster_operations_controller
import pcluster.api.controllers.image_operations_controller


def to_kebab_case(input):
    """Convert a string into its snake case representation."""
    str1 = re.sub("(.)([A-Z][a-z]+)", r"\1-\2", input).replace('_', '-')
    return re.sub("([a-z0-9])([A-Z])", r"\1-\2", str1).lower()


def to_snake_case(input):
    """Convert a string into its snake case representation."""
    str1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", input).replace('-', '_')
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", str1).lower()


def bool_converter(in_str):
    """Takes a boolean string and converts it into a boolean value."""
    return in_str not in {'false', 'False', 'FALSE', False}


def read_file_b64(path):
    """Takes file path, reads the file and converts to base64 encoded string"""
    with open(path) as file:
        file_data = file.read()
    return base64.b64encode(file_data.encode('utf-8')).decode('utf-8')


def _resolve_ref(spec, subspec):
    if '$ref' in subspec:
        schema_ref = subspec['$ref'].replace('#/components/schemas/', '')
        subspec.update(spec['components']['schemas'][schema_ref])
    return subspec


def _resolve_param(spec, param):
    _resolve_ref(spec, param['schema'])

    new_param = {'name': to_kebab_case(param['name']),
                 'body': False}
    copy_keys = {'description', 'required'}
    new_param.update({k: v for k, v in param.items() if k in copy_keys})

    schema_keys = {'enum', 'type'}
    new_param.update({k: v for k, v in param['schema'].items() if k in schema_keys})

    if 'items' in param['schema']:
        new_param['multi'] = True
        schema = _resolve_ref(spec, param['schema']['items'])
        if 'enum' in schema:
            new_param['enum'] = schema['enum']
    return new_param


def _resolve_body(spec, operation):
    body_content = _resolve_ref(spec, operation['requestBody']['content']
                                ['application/json']['schema'])

    required = set(body_content.get('required', []))
    new_params = []
    for param_name, param_data in body_content['properties'].items():
        _resolve_ref(spec, param_data)

        new_param = {'name': to_kebab_case(param_name),
                     'body': True,
                     'required': param_name in required}
        copy_keys = {'description', 'type', 'enum'}
        new_param.update({k: v for k, v in param_data.items() if k in copy_keys})

        if param_data.get('format', None) == 'byte':
            new_param['type'] = 'byte'
        new_params.append(new_param)

    return new_params


def load_model():
    """Reads the openapi specification and converts it into a model, resolving
    references and pulling out relevant properties for CLI parsing and function
    invocation."""
    with pkg_resources.open_text(openapi, "openapi.yaml") as spec_file:
        spec = yaml.safe_load(spec_file.read())

    model = {}

    for _path, eps in spec['paths'].items():
        for _method, operation in eps.items():
            op_name = to_kebab_case(operation['operationId'])

            params = []
            for param in operation['parameters']:
                params.append(_resolve_param(spec, param))

            if 'requestBody' in operation:
                params.extend(_resolve_body(spec, operation))

            module_name = operation['x-openapi-router-controller']
            func_name = to_snake_case(op_name)
            func = get_function_from_name(f"{module_name}.{func_name}")

            model[op_name] = {'params': params, 'func': func}
            if 'description' in operation:
                model[op_name]['description'] = operation['description']

    return model


def convert_args(model, op_name, args_in):
    """Takes a model, the name of the operation and the arguments
    provided by argparse and converts the parameters into a format
    that is suitable to be called in the controllers."""
    body = {}
    kwargs = {}
    pos_args = []
    for param in model[op_name]['params']:
        param_name = to_snake_case(param['name'])
        value = args_in.pop(param_name)

        if param['body']:
            param_name = camelcase(param_name)
            param_name = param_name[0].lower() + param_name[1:]
            body[param_name] = value
        elif param.get('required', False):
            pos_args.append(value)
        else:
            kwargs[param_name] = value

    kwargs.update(args_in)

    return body, pos_args, kwargs


def list_clusters_middleware(func, _body, pos_args, kwargs):
    time_func = kwargs.pop('time', False)
    start = time.time()
    ret = func(*pos_args, **kwargs)
    if time_func:
        pprint(ret)
        print(f"Took: {time.time() - start} ms", )
        return None  # supress default print
    else:
        return ret


def dispatch(model, args):
    """Dispatches to a controller function when the arguments have an
    operation specified."""
    args_dict = args.__dict__
    operation = args.operation
    dispatch_func = model[operation]['func']
    del args_dict['func']
    del args_dict['operation']
    body, pos_args, kwargs = convert_args(model, operation, args_dict)

    if len(body):
        dispatch_func = partial(dispatch_func, body)

    middleware = {'list-clusters': list_clusters_middleware}

    if operation in middleware:
        ret = middleware[operation](dispatch_func, body, pos_args, kwargs)
    else:
        ret = dispatch_func(*pos_args, **kwargs)

    if ret:
        pprint(ret)


def gen_parser(model):
    """Takes a model and returns an ArgumentParser for converting command line
    arguments into values based on that model."""
    desc = ("pcluster is the AWS ParallelCluster CLI and permits "
            "launching and management of HPC clusters in the AWS cloud.")
    epilog = 'For command specific flags, please run: "pcluster [command] --help"'
    parser = argparse.ArgumentParser(description=desc, epilog=epilog)
    subparsers = parser.add_subparsers(help="", required=True, title='COMMANDS',
                                       dest='operation', metavar="")
    type_map = {'int': int, 'boolean': bool_converter, 'byte': read_file_b64}
    parser_map = {'subparser': subparsers}

    for op_name, operation in model.items():
        op_help = operation.get('description', f"{op_name} command help")
        subparser = subparsers.add_parser(op_name, help=op_help, description=op_help)
        parser_map[op_name] = subparser

        for param in operation['params']:
            help = param.get('description', '')
            metavar = param['name'].upper() if len(param.get('enum', [])) > 4 else None
            subparser.add_argument(f"--{param['name']}",
                                   required=param.get('required', False),
                                   choices=param.get('enum', None),
                                   nargs='+' if 'multi' in param else None,
                                   type=type_map.get(param.get('type')),
                                   metavar=metavar,
                                   help=help)

        subparser.set_defaults(func=partial(dispatch, model))
    return parser, parser_map


def add_cluster_commands(model, subparsers):
    """Generically adds CLI commmands by instantiating the objects."""
    # TODO: remove this once the implementations have been deleted
    api_implemented = {'status', 'create', 'delete', 'instances',
                       'list', 'start', 'stop', 'update'}
    for _name, obj in inspect.getmembers(cluster_commands):
        if inspect.isclass(obj) and issubclass(obj, CliCommand):
            if (hasattr(obj, 'name')
                    and obj.name not in model
                    and obj.name not in api_implemented):
                obj(subparsers)


def add_cli_commands(model, parser_map):
    """Adds additional CLI arguments that don't belong to the API."""
    subparsers = parser_map['subparser']
    VersionCommand(subparsers)
    add_cluster_commands(model, subparsers)

    # TODO: just for testing purposes
    parser_map['list-clusters'].add_argument("--time", action='store_true',
                                             help="Time the command to finish.")


def main():
    model = load_model()
    parser, parser_map = gen_parser(model)
    add_cli_commands(model, parser_map)
    args, extra_args = parser.parse_known_args()

    if extra_args and (not hasattr(args, 'expects_extra_args') or not args.expects_extra_args):
        parser.print_usage()
        print("Invalid arguments %s" % extra_args)
        sys.exit(1)

    if args.operation in model:
        args.func(args)
    else:
        args.func(args, extra_args)


if __name__ == "__main__":
    main()
