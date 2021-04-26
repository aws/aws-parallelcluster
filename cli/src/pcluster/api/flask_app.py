# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import json

import connexion
from connexion import ProblemException
from connexion.decorators.validation import ParameterValidator
from flask import Response
from werkzeug.exceptions import HTTPException

from pcluster.api import encoder
from pcluster.api.errors import ParallelClusterApiException


class CustomParameterValidator(ParameterValidator):
    """Override the Connexion ParameterValidator to remove JSON schema details on errors."""

    @staticmethod
    def validate_parameter(parameter_type, value, param, param_name=None):
        """
        Validate request parameter.

        The default validator provided by connexion returns a verbose error on failures. Overriding this method
        in order to strip additional details we do not want to propagate to the user.
        """
        error = super(CustomParameterValidator, CustomParameterValidator).validate_parameter(
            parameter_type, value, param, param_name
        )
        # When the request fails validation against the object schema the default returned error contains a first
        # line with a high level error messaging and then subsequent lines with the JSON schema details.
        # Stripping the JSON schema related part in order to not return this in the response.
        if error and "Failed validating" in error:
            error = error.split("\n", 1)[0]
        return error


class ParallelClusterFlaskApp:
    """Flask app that implements the ParallelCluster API."""

    def __init__(self, swagger_ui: bool = False, validate_responses=False):
        options = {"swagger_ui": swagger_ui}

        app = connexion.FlaskApp(__name__, specification_dir="openapi/", skip_error_handlers=True)
        app.app.json_encoder = encoder.JSONEncoder
        app.add_api(
            "openapi.yaml",
            arguments={"title": "ParallelCluster"},
            pythonic_params=True,
            options=options,
            validate_responses=validate_responses,
            validator_map={"parameter": CustomParameterValidator},
        )
        app.add_error_handler(HTTPException, self._render_http_exception)
        app.add_error_handler(ProblemException, self._render_problem_exception)
        app.add_error_handler(ParallelClusterApiException, self._render_parallel_cluster_api_exception)
        self.app = app

    @staticmethod
    def _render_http_exception(exception: HTTPException):
        """Render a HTTPException according to ParallelCluster API specs."""
        return Response(
            response=json.dumps({"message": exception.description}), status=exception.code, mimetype="application/json"
        )

    @staticmethod
    def _render_problem_exception(exception: ProblemException):
        """Render a ProblemException according to ParallelCluster API specs."""
        # Connexion does not return a clear error message on missing request body
        if "None is not of type 'object'" in exception.detail:
            exception.detail = "request body is required"
        return Response(
            response=json.dumps({"message": f"{exception.title}: {exception.detail}"}),
            status=exception.status,
            mimetype="application/json",
        )

    @staticmethod
    def _render_parallel_cluster_api_exception(exception: ParallelClusterApiException):
        """Render a ParallelClusterApiException according to ParallelCluster API specs."""
        return Response(
            response=json.dumps(exception.content.to_dict()), status=exception.code, mimetype="application/json"
        )

    def start_local_server(self, port: int = 8080, debug: bool = False):
        """Start a local development Flask server."""
        self.app.run(port=port, debug=debug)


if __name__ == "__main__":
    ParallelClusterFlaskApp(swagger_ui=True, validate_responses=False).start_local_server(debug=False)
