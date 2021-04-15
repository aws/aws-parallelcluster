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

from os import environ
from typing import Any, Dict

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

from api.awslambda.serverless_wsgi import handle_request
from api.flask_app import ParallelClusterFlaskApp

logger = Logger(service="pcluster", location="%(filename)s:%(lineno)s - %(funcName)s()")

profile = environ.get("PROFILE", "prod")
is_dev_profile = profile == "dev"
logger.info(f"Running with profile: {profile}")

if is_dev_profile:
    logger.info("Enabled debug mode")
    environ["FLASK_ENV"] = "development"
    environ["FLASK_DEBUG"] = "1"

# Initialize as a global to re-use across Lambda invocations
pcluster_api = ParallelClusterFlaskApp(swagger_ui=is_dev_profile, validate_responses=is_dev_profile)


@logger.inject_lambda_context(log_event=is_dev_profile)
def lambda_handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    try:
        return handle_request(pcluster_api.app, event, context)
    except Exception:
        logger.exception("Unexpected exception")
        raise
