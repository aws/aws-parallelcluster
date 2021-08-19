# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import os
from os import environ
from typing import Any, Dict

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.ext.flask.middleware import XRayMiddleware

from pcluster.api.awslambda.serverless_wsgi import handle_request
from pcluster.api.flask_app import ParallelClusterFlaskApp

logger = Logger(service="pcluster", location="%(filename)s:%(lineno)s:%(funcName)s()")
tracer = Tracer(service="pcluster")

# Initialize as a global to re-use across Lambda invocations
pcluster_api = None  # pylint: disable=invalid-name

profile = environ.get("PROFILE", "prod")
is_dev_profile = profile == "dev"

if is_dev_profile:
    logger.info("Running with dev profile")
    environ["FLASK_ENV"] = "development"
    environ["FLASK_DEBUG"] = "1"


@tracer.capture_method
def _init_flask_app():
    return ParallelClusterFlaskApp(swagger_ui=is_dev_profile, validate_responses=is_dev_profile)


@logger.inject_lambda_context(log_event=is_dev_profile)
@tracer.capture_lambda_handler
def lambda_handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    try:
        global pcluster_api  # pylint: disable=global-statement,invalid-name
        if not pcluster_api:
            logger.info("Initializing Flask Application")
            pcluster_api = _init_flask_app()
            # Instrument X-Ray recorder to trace requests served by the Flask application
            if event.get("version") == "2.0":
                xray_recorder.configure(service="ParallelCluster Flask App")
                XRayMiddleware(pcluster_api.flask_app, xray_recorder)
        # Setting default region to region where lambda function is executed
        os.environ["AWS_DEFAULT_REGION"] = os.environ["AWS_REGION"]
        return handle_request(pcluster_api.app, event, context)
    except Exception as e:
        logger.critical("Unexpected exception: %s", e, exc_info=True)
        raise Exception("Unexpected fatal exception. Please look at API logs for details on the encountered failure.")
