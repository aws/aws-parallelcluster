# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from abc import ABC

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
    code: int = None
    content: Model = None


class CreateClusterBadRequestException(ParallelClusterApiException):
    code = 400

    def __init__(self, content: CreateClusterBadRequestExceptionResponseContent):
        super().__init__()
        self.content = content


class BuildImageBadRequestException(ParallelClusterApiException):
    code = 400

    def __init__(self, content: BuildImageBadRequestExceptionResponseContent):
        super().__init__()
        self.content = content


class UpdateClusterBadRequestException(ParallelClusterApiException):
    code = 400

    def __init__(self, content: UpdateClusterBadRequestExceptionResponseContent):
        super().__init__()
        self.content = content
