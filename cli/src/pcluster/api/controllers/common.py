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
from typing import List, Optional, Set, Union

import boto3
from pkg_resources import packaging

from pcluster.api.errors import (
    BadRequestException,
    ConflictException,
    InternalServiceException,
    LimitExceededException,
    NotFoundException,
    ParallelClusterApiException,
)
from pcluster.aws.common import BadRequestError, LimitExceededError, StackNotFoundError
from pcluster.config.common import AllValidatorsSuppressor, TypeMatchValidatorsSuppressor, ValidatorSuppressor
from pcluster.constants import SUPPORTED_REGIONS
from pcluster.models.cluster import Cluster
from pcluster.models.common import BadRequest, Conflict, LimitExceeded, NotFound, parse_config
from pcluster.utils import get_installed_version, to_utc_datetime

LOGGER = logging.getLogger(__name__)


def _set_region(region):
    if not region:
        raise BadRequestException("region needs to be set")
    if region not in SUPPORTED_REGIONS:
        raise BadRequestException(f"invalid or unsupported region '{region}'")

    LOGGER.info("Setting AWS Region to %s", region)
    os.environ["AWS_DEFAULT_REGION"] = region


def configure_aws_region_from_config(region: Union[None, str], config_str: str):
    """Set the region based on either the configuration or theregion parameter."""
    # Allow parsing errors to pass through as they will be caught by later functions
    # which can provide more specific error text based on the operation.
    try:
        config_region = parse_config(config_str).get("Region")
    except Exception:
        config_region = None
    if region and config_region and region != config_region:
        raise BadRequestException("region is set in both parameter and configuration and conflicts.")

    _set_region(region or config_region or boto3.Session().region_name)


def configure_aws_region():
    """
    Handle region validation and configuration for API controllers.

    When a controller is decorated with @configure_aws_region, the region value passed either as a query string
    argument or as a body parameter is validated and then set in the environment so that all AWS clients make use
    of it.
    """

    def _decorator_validate_region(func):
        @functools.wraps(func)
        def _wrapper_validate_region(*args, **kwargs):
            _set_region(kwargs.get("region") or boto3.Session().region_name)
            return func(*args, **kwargs)

        return _wrapper_validate_region

    return _decorator_validate_region


def http_success_status_code(status_code: int = 200):
    """
    Set the status code for successful API responses.

    It can be used as a decorator for API controller methods that need to return a status code different
    from 200 for successful requests.

    :param status_code: status code to return for successful requests
    """

    def _decorator_http_success_status_code(func):
        @functools.wraps(func)
        def _wrapper_http_success_status_code(*args, **kwargs):
            return func(*args, **kwargs), status_code

        return _wrapper_http_success_status_code

    return _decorator_http_success_status_code


def check_cluster_version(cluster: Cluster, exact_match: bool = False) -> bool:
    if not cluster.stack.version:
        return False

    if exact_match:
        return packaging.version.parse(cluster.stack.version) == packaging.version.parse(get_installed_version())
    else:
        return (
            packaging.version.parse(packaging.version.parse(get_installed_version()).base_version)
            >= packaging.version.parse(cluster.stack.version)
            >= packaging.version.parse("3.0.0a0")
        )


def validate_cluster(cluster: Cluster):
    try:
        if not check_cluster_version(cluster):
            raise BadRequestException(
                f"Cluster '{cluster.name}' belongs to an incompatible ParallelCluster major version."
            )
    except StackNotFoundError:
        raise NotFoundException(
            f"Cluster '{cluster.name}' does not exist or belongs to an incompatible ParallelCluster major version."
        )


def validate_timestamp(date_str: str, ts_name: str = "Time"):
    try:
        return to_utc_datetime(date_str)
    except Exception:
        raise BadRequestException(
            f"{ts_name} filter must be in the ISO 8601 format: YYYY-MM-DDThh:mm:ssZ. "
            "(e.g. 1984-09-15T19:20:30Z or 1984-09-15)."
        )


def convert_errors():
    def _decorate_api(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ParallelClusterApiException as e:
                raise e
            except (LimitExceeded, LimitExceededError) as e:
                raise LimitExceededException(str(e)) from e
            except (BadRequest, BadRequestError) as e:
                raise BadRequestException(str(e)) from e
            except Conflict as e:
                raise ConflictException(str(e)) from e
            except NotFound as e:
                raise NotFoundException(str(e)) from e
            except Exception as e:
                raise InternalServiceException(str(e)) from e

        return wrapper

    return _decorate_api


def get_validator_suppressors(suppress_validators: Optional[List[str]]) -> Set[ValidatorSuppressor]:
    validator_suppressors: Set[ValidatorSuppressor] = set()
    if not suppress_validators:
        return validator_suppressors

    validator_types_to_suppress = set()
    for suppress_validator_expression in suppress_validators:
        if suppress_validator_expression == "ALL":
            validator_suppressors.add(AllValidatorsSuppressor())
        elif suppress_validator_expression.startswith("type:"):
            validator_types_to_suppress.add(suppress_validator_expression[len("type:") :])  # noqa: E203

    if validator_types_to_suppress:
        validator_suppressors.add(TypeMatchValidatorsSuppressor(validator_types_to_suppress))

    return validator_suppressors
