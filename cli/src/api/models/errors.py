# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from abc import ABC

from api.models import (
    BuildImageBadRequestExceptionResponseContent,
    CreateClusterBadRequestExceptionResponseContent,
    UpdateClusterBadRequestExceptionResponseContent,
)
from api.models.base_model_ import Model


class ParallelClusterApiException(ABC, Exception):
    code: int = None
    content: Model = None


class CreateClusterBadRequestException(ParallelClusterApiException):
    code = 400

    def __init__(self, content: CreateClusterBadRequestExceptionResponseContent):
        super(CreateClusterBadRequestException, self).__init__()
        self.content = content


class BuildImageBadRequestException(ParallelClusterApiException):
    code = 400

    def __init__(self, content: BuildImageBadRequestExceptionResponseContent):
        super(BuildImageBadRequestException, self).__init__()
        self.content = content


class UpdateClusterBadRequestException(ParallelClusterApiException):
    code = 400

    def __init__(self, content: UpdateClusterBadRequestExceptionResponseContent):
        super(UpdateClusterBadRequestException, self).__init__()
        self.content = content
