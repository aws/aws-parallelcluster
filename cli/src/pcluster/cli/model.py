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
import functools
import importlib
import json

import jmespath

from pcluster.api import encoder, openapi
from pcluster.cli.exceptions import APIOperationException
from pcluster.utils import to_kebab_case, to_snake_case, yaml_load

# For importing package resources
try:
    import importlib.resources as pkg_resources  # pylint: disable=ungrouped-imports
except ImportError:
    import importlib_resources as pkg_resources


def _param_overrides(operation, param):
    """Provide updates to the model that are specific to the CLI."""
    overrides = {
        "create-cluster": {"clusterConfiguration": {"type": "file"}},
        "update-cluster": {"clusterConfiguration": {"type": "file"}},
        "build-image": {"imageConfiguration": {"type": "file"}},
    }

    try:
        return overrides[to_kebab_case(operation["operationId"])][param]
    except KeyError:
        return {}


def _resolve_ref(spec, subspec):
    """Look up a reference (e.g. $ref)in the specification."""
    if "$ref" in subspec:
        schema_ref = subspec["$ref"].replace("#/components/schemas/", "")
        subspec.update(spec["components"]["schemas"][schema_ref])
    return subspec


def _resolve_param(spec, param):
    _resolve_ref(spec, param["schema"])

    new_param = {"name": to_kebab_case(param["name"]), "body": False}
    copy_keys = {"description", "required"}
    new_param.update({k: v for k, v in param.items() if k in copy_keys})

    schema = param["schema"]
    if "items" in param["schema"]:
        new_param["multi"] = True
        schema = _resolve_ref(spec, param["schema"]["items"])

    schema_keys = {"enum", "type", "pattern"}
    new_param.update({k: v for k, v in schema.items() if k in schema_keys})

    return new_param


def _resolve_body(spec, operation):
    body_content = _resolve_ref(spec, operation["requestBody"]["content"]["application/json"]["schema"])

    required = set(body_content.get("required", []))
    new_params = []
    for param_name, param_data in body_content["properties"].items():
        _resolve_ref(spec, param_data)

        new_param = {"name": to_kebab_case(param_name), "body": True, "required": param_name in required}
        copy_keys = {"description", "type", "enum", "pattern"}
        new_param.update({k: v for k, v in param_data.items() if k in copy_keys})
        if param_data.get("format", None) == "byte":
            new_param["type"] = "byte"
        new_param.update(_param_overrides(operation, param_name))
        new_params.append(new_param)

    return new_params


def package_spec():
    """Load the OpenAPI specification from the package."""
    with pkg_resources.open_text(openapi, "openapi.yaml") as spec_file:
        return yaml_load(spec_file.read())


def load_model(spec):
    """Read the openapi specification and convert it into a model.

    In the process, resolve references and pull out relevant properties for CLI
    parsing and function invocation.

    The output data structure is a map for operationId to data shaped liked the
    following:

    {'list-clusters':
      {'description': 'Retrieve the list of existing clusters ...',
       'func': 'pcluster.api.controllers.cluster_operations_controller',
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
       ...}
    """
    model = {}

    for _path, eps in spec["paths"].items():
        for _method, operation in eps.items():
            op_name = to_kebab_case(operation["operationId"])

            params = []
            for param in operation["parameters"]:  # add query params
                params.append(_resolve_param(spec, param))

            if "requestBody" in operation:  # add body
                params.extend(_resolve_body(spec, operation))

            # add controller function
            module_name = operation["x-openapi-router-controller"]
            func_name = to_snake_case(op_name)
            func = f"{module_name}.{func_name}"

            model[op_name] = {"params": params, "func": func}
            if "description" in operation:
                model[op_name]["description"] = operation["description"]
            try:
                body_name = operation["requestBody"]["content"]["application/json"]["schema"]["x-body-name"]
                model[op_name]["body_name"] = body_name
            except KeyError:
                pass

    return model


def get_function_from_name(function_name):
    """
    Get function by fully qualified name (e.g. "mymodule.myobj.myfunc").

    :type function_name: str
    """
    if function_name is None:
        raise ValueError("Empty function name")

    if "." in function_name:
        module_name, attr_path = function_name.rsplit(".", 1)
    else:
        module_name = ""
        attr_path = function_name

    module = None
    last_import_error = None

    while not module:
        try:
            module = importlib.import_module(module_name)
        except ImportError as import_error:
            last_import_error = import_error
            if "." in module_name:
                module_name, attr_path1 = module_name.rsplit(".", 1)
                attr_path = "{0}.{1}".format(attr_path1, attr_path)
            else:
                raise
    try:
        function = deep_getattr(module, attr_path)
    except AttributeError:
        if last_import_error:
            raise last_import_error
        raise
    return function


def deep_getattr(obj, attr):
    """Recurse through an attribute chain to get the ultimate value."""
    attrs = attr.split(".")

    return functools.reduce(getattr, attrs, obj)


def call(func_str, *args, **kwargs):
    """Look up the function by controller.func string and call function.

    Function name specified as e.g.:
     - pcluster.cli.controllers.cluster_operations_controller.list_clusters

    Ignore status-codes on the command line as errors are handled through
    exceptions, but some functions return 202 which causes the return to be a
    tuple (instead of an object). Also uses the flask json-ifier to ensure data
    is converted the same as the API.
    """
    query = kwargs.pop("query", None)
    func = get_function_from_name(func_str)
    ret = func(*args, **kwargs)
    if isinstance(ret, tuple):
        ret, status_code = ret
        if status_code >= 400:
            data = json.loads(encoder.JSONEncoder().encode(ret))
            raise APIOperationException(data)
    data = json.loads(encoder.JSONEncoder().encode(ret))
    return jmespath.search(query, data) if query else data
