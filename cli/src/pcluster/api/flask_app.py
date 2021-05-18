# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import json
import logging

import connexion
from connexion import ProblemException
from connexion.decorators.validation import ParameterValidator
from flask import Response, request
from werkzeug.exceptions import HTTPException

from pcluster.api import encoder
from pcluster.api.errors import (
    BadRequestException,
    InternalServiceException,
    LimitExceededException,
    ParallelClusterApiException,
)
from pcluster.aws.common import AWSClientError
from pcluster.utils import Cache

LOGGER = logging.getLogger(__name__)


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

        self.app = connexion.FlaskApp(__name__, specification_dir="openapi/", skip_error_handlers=True)
        self.flask_app = self.app.app
        self.flask_app.json_encoder = encoder.JSONEncoder
        self.app.add_api(
            "openapi.yaml",
            arguments={"title": "ParallelCluster"},
            pythonic_params=True,
            options=options,
            validate_responses=validate_responses,
            validator_map={"parameter": CustomParameterValidator},
        )
        self.app.add_error_handler(HTTPException, self._handle_http_exception)
        self.app.add_error_handler(ProblemException, self._handle_problem_exception)
        self.app.add_error_handler(ParallelClusterApiException, self._handle_parallel_cluster_api_exception)
        self.app.add_error_handler(AWSClientError, self._handle_aws_client_error)
        self.app.add_error_handler(Exception, self._handle_unexpected_exception)

        @self.flask_app.before_request
        def _clear_cache():
            # Cache is meant to be reused only within a single request
            Cache.clear_all()

        @self.flask_app.before_request
        def _log_request():  # pylint: disable=unused-variable
            LOGGER.info("Handling request: %s %s", request.method, request.full_path)

        @self.flask_app.after_request
        def _log_response(response: Response):  # pylint: disable=unused-variable
            LOGGER.info(
                "Responding with status code %s to request %s %s",
                response.status_code,
                request.method,
                request.full_path,
            )
            return response

    @staticmethod
    def _handle_http_exception(exception: HTTPException):
        """Render a HTTPException according to ParallelCluster API specs."""
        ParallelClusterFlaskApp._log_exception(exception.code, exception.description)
        return Response(
            response=json.dumps({"message": exception.description}), status=exception.code, mimetype="application/json"
        )

    @staticmethod
    def _handle_problem_exception(exception: ProblemException):
        """Render a ProblemException according to ParallelCluster API specs."""
        # Connexion does not return a clear error message on missing request body
        if "None is not of type 'object'" in exception.detail:
            exception.detail = "request body is required"
        message = f"{exception.title}: {exception.detail}"
        ParallelClusterFlaskApp._log_exception(exception.status, message)
        return Response(
            response=json.dumps({"message": message}),
            status=exception.status,
            mimetype="application/json",
        )

    @staticmethod
    def _handle_parallel_cluster_api_exception(exception: ParallelClusterApiException):
        """Render a ParallelClusterApiException according to ParallelCluster API specs."""
        message = json.dumps(exception.content.to_dict())
        ParallelClusterFlaskApp._log_exception(exception.code, message)
        return Response(response=message, status=exception.code, mimetype="application/json")

    @staticmethod
    def _handle_unexpected_exception(exception: Exception):
        """Handle an unexpected exception."""
        LOGGER.critical("Unexpected exception: %s", exception, exc_info=True)
        return Response(
            response=json.dumps(
                {
                    "message": "Unexpected fatal exception. "
                    "Please look at the application logs for details on the encountered failure."
                }
            ),
            status=500,
            mimetype="application/json",
        )

    @staticmethod
    def _handle_aws_client_error(exception: AWSClientError):
        """Transform a AWSClientError into a valid API error."""
        if exception.error_code == AWSClientError.ErrorCode.VALIDATION_ERROR.value:
            return ParallelClusterFlaskApp._handle_parallel_cluster_api_exception(BadRequestException(str(exception)))
        if exception.error_code in AWSClientError.ErrorCode.throttling_error_codes():
            return ParallelClusterFlaskApp._handle_parallel_cluster_api_exception(
                LimitExceededException(str(exception))
            )
        return ParallelClusterFlaskApp._handle_parallel_cluster_api_exception(
            InternalServiceException(f"Failed when calling AWS service in {exception.function_name}: {exception}")
        )

    @staticmethod
    def _log_exception(code, message):
        LOGGER.log(
            logging.ERROR if code >= 500 else logging.INFO,
            "Handling exception (status code %s): %s",
            code,
            message,
            exc_info=code >= 500,
        )

    def start_local_server(self, port: int = 8080, debug: bool = False):
        """Start a local development Flask server."""
        self.app.run(port=port, debug=debug)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ParallelClusterFlaskApp(swagger_ui=True, validate_responses=True).start_local_server(debug=True)
