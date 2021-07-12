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

import yaml
from functools import lru_cache
import json
from connexion.utils import get_function_from_name
from pcluster.utils import to_kebab_case, to_snake_case
from pcluster.api import openapi
from pcluster.api import encoder

# For importing package resources
try:
    import importlib.resources as pkg_resources
except ImportError:
    import importlib_resources as pkg_resources


def _resolve_ref(spec, subspec):
    """Looks up a reference in the specification"""
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

    schema = param['schema']
    if 'items' in param['schema']:
        new_param['multi'] = True
        schema = _resolve_ref(spec, param['schema']['items'])

    schema_keys = {'enum', 'type', 'pattern'}
    new_param.update({k: v for k, v in schema.items() if k in schema_keys})

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
        copy_keys = {'description', 'type', 'enum', 'pattern'}
        new_param.update({k: v for k, v in param_data.items() if k in copy_keys})
        if param_data.get('format', None) == 'byte':
            new_param['type'] = 'byte'
        new_params.append(new_param)

    return new_params


@lru_cache
def package_spec():
    """Load the OpenAPI specification from the package."""
    with pkg_resources.open_text(openapi, "openapi.yaml") as spec_file:
        return yaml.safe_load(spec_file.read())


@lru_cache
def load_model(spec):
    """Reads the openapi specification and converts it into a model, resolving
    references and pulling out relevant properties for CLI parsing and function
    invocation.

    The output data structure is a map for operationId to data shaped liked the
    following:

    {'list-clusters':
      {'description': 'Retrieve the list of existing clusters ...',
       'func': <function list_clusters at 0x7f1445b87040>,
       'params': [{'body': False,
                   'description': 'List clusters deployed to ...',
                   'name': 'region',
                   'required': False,
                   'type': 'string'},
                  {'body': False,
                   'description': 'Filter by cluster status.',
                   'enum': ['CREATE_IN_PROGRESS',
                            'CREATE_COMPLETE',
                            ...],
                   'multi': True,
                   'name': 'cluster-status',
                   'required': False,
                   'type': 'string'}]},
       ...}"""

    model = {}

    for _path, eps in spec['paths'].items():
        for _method, operation in eps.items():
            op_name = to_kebab_case(operation['operationId'])

            params = []
            for param in operation['parameters']:               # add query params
                params.append(_resolve_param(spec, param))

            if 'requestBody' in operation:                      # add body
                params.extend(_resolve_body(spec, operation))

            # add controller function
            module_name = operation['x-openapi-router-controller']
            func_name = to_snake_case(op_name)
            func = f"{module_name}.{func_name}"

            model[op_name] = {'params': params, 'func': func}
            if 'description' in operation:
                model[op_name]['description'] = operation['description']

    return model


def call(func_str, *args, **kwargs):
    """Looks up the function by controller.func string (e.g.
    pcluster.cli.controllers.cluster_operations_controller.list_clusters),
    Then calls the function.

    Ignore status-codes on the command line as errors are handled through
    exceptions, but some functions return 202 which causes the return to be a
    tuple (instead of an object). Also uses the flask json-ifier to ensure data
    is converted the same as the API.
    """
    func = get_function_from_name(func_str)
    ret = func(*args, **kwargs)
    ret = ret[0] if isinstance(ret, tuple) else ret
    return json.loads(encoder.JSONEncoder().encode(ret))
