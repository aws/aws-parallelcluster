#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import functools
import logging
import os

from flask import request

from pcluster.api.errors import BadRequestException
from pcluster.constants import SUPPORTED_REGIONS

LOGGER = logging.getLogger(__name__)


def configure_aws_region(is_query_string_arg: bool = True):
    """
    Handle region validation and configuration for API controllers.

    When a controller is decorated with @configure_aws_region, the region value passed either as a query stirng
    argument or as a body parameter is validated and then set in the environment so that all AWS clients make use
    of it.

    :param is_query_string_arg: set to False when the region configuration is in the request body
    """

    def _decorator_validate_region(func):
        @functools.wraps(func)
        def _wrapper_validate_region(*args, **kwargs):
            region = kwargs.get("region") if is_query_string_arg else request.get_json().get("region")
            if not region:
                region = os.environ.get("AWS_DEFAULT_REGION")

            if not region:
                raise BadRequestException("region needs to be set")
            if region not in SUPPORTED_REGIONS:
                raise BadRequestException(f"invalid or unsupported region '{region}'")

            LOGGER.info("Setting AWS Region to %s", region)
            os.environ["AWS_DEFAULT_REGION"] = region

            return func(*args, **kwargs)

        return _wrapper_validate_region

    return _decorator_validate_region
