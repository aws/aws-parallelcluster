# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from abc import ABC

from pcluster.api.models import (
    BadRequestExceptionResponseContent,
    ConflictExceptionResponseContent,
    DryrunOperationExceptionResponseContent,
    InternalServiceExceptionResponseContent,
    LimitExceededExceptionResponseContent,
    NotFoundExceptionResponseContent,
)
from pcluster.api.models.base_model_ import Model
from pcluster.api.models.build_image_bad_request_exception_response_content import (
    BuildImageBadRequestExceptionResponseContent,
)
from pcluster.api.models.create_cluster_bad_request_exception_response_content import (
    CreateClusterBadRequestExceptionResponseContent,
)
from pcluster.api.models.update_cluster_bad_request_exception_response_content import (
    UpdateClusterBadRequestExceptionResponseContent,
)


class ParallelClusterApiException(ABC, Exception):
    """Base class for ParallelCluster Api exceptions."""

    code: int = None
    content: Model = None

    def __init__(self, content: Model):
        super().__init__()
        self.content = content


class CreateClusterBadRequestException(ParallelClusterApiException):
    """Exception raised when receiving an invalid cluster config on a create operation."""

    code = 400

    def __init__(self, content: CreateClusterBadRequestExceptionResponseContent):
        super().__init__(content)


class BuildImageBadRequestException(ParallelClusterApiException):
    """Exception raised when receiving an invalid image config on a create operation."""

    code = 400

    def __init__(self, content: BuildImageBadRequestExceptionResponseContent):
        super().__init__(content)


class UpdateClusterBadRequestException(ParallelClusterApiException):
    """Exception raised when receiving an invalid cluster config on an update operation."""

    code = 400

    def __init__(self, content: UpdateClusterBadRequestExceptionResponseContent):
        super().__init__(content)


class BadRequestException(ParallelClusterApiException):
    """Exception raised for invalid requests."""

    code = 400

    def __init__(self, content: str):
        super().__init__(BadRequestExceptionResponseContent(f"Bad Request: {content}"))


class InternalServiceException(ParallelClusterApiException):
    """Exception raised for internal service errors."""

    code = 500

    def __init__(self, content: str):
        super().__init__(InternalServiceExceptionResponseContent(content))


class LimitExceededException(ParallelClusterApiException):
    """Exception raised when the client is sending more than the allowed number of requests per unit of time."""

    code = 429

    def __init__(self, content: str):
        super().__init__(LimitExceededExceptionResponseContent(content))


class NotFoundException(ParallelClusterApiException):
    """Exception raised when the queried resource does not exist."""

    code = 404

    def __init__(self, content: str):
        super().__init__(NotFoundExceptionResponseContent(content))


class DryrunOperationException(ParallelClusterApiException):
    """Exception raised when a dryrun operation would have succeeded without the dryrun flag."""

    code = 412

    def __init__(self, content: str = "Request would have succeeded, but DryRun flag is set."):
        super().__init__(DryrunOperationExceptionResponseContent(content))


class ConflictException(ParallelClusterApiException):
    """This exception is thrown when a client request to create/modify content would result in a conflict."""

    code = 409

    def __init__(self, content: str):
        super().__init__(ConflictExceptionResponseContent(content))
