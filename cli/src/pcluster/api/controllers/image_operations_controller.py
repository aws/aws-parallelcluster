# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=W0613
import functools
import os as os_lib
from datetime import datetime

from pcluster.api.controllers.common import configure_aws_region, parse_config
from pcluster.api.converters import (
    cloud_formation_status_to_image_status,
    validation_results_to_config_validation_errors,
)
from pcluster.api.errors import (
    BadRequestException,
    BuildImageBadRequestException,
    InternalServiceException,
    LimitExceededException,
    NotFoundException,
    ParallelClusterApiException,
)
from pcluster.api.models import (
    BuildImageBadRequestExceptionResponseContent,
    BuildImageRequestContent,
    BuildImageResponseContent,
    CloudFormationStatus,
    DescribeImageResponseContent,
    DescribeOfficialImagesResponseContent,
    ImageBuilderImageStatus,
    ImageConfigurationStructure,
    ImageInfoSummary,
    ImageStatusFilteringOption,
    ListImagesResponseContent,
)
from pcluster.api.models.delete_image_response_content import DeleteImageResponseContent
from pcluster.api.models.image_build_status import ImageBuildStatus
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import BadRequestError, LimitExceededError
from pcluster.models.imagebuilder import (
    BadRequestImageBuilderActionError,
    BadRequestImageError,
    ConflictImageBuilderActionError,
    ImageBuilder,
    LimitExceededImageBuilderActionError,
    LimitExceededImageError,
    NonExistingImageError,
)
from pcluster.models.imagebuilder_resources import (
    BadRequestStackError,
    ImageBuilderStack,
    LimitExceededStackError,
    NonExistingStackError,
)
from pcluster.validators.common import FailureLevel


def convert_imagebuilder_errors():
    def _decorate_image_operations_api(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ParallelClusterApiException as e:
                error = e
            except (
                LimitExceededError,
                LimitExceededImageError,
                LimitExceededStackError,
                LimitExceededImageBuilderActionError,
            ) as e:
                error = LimitExceededException(str(e))
            except (
                BadRequestError,
                BadRequestImageError,
                BadRequestStackError,
                BadRequestImageBuilderActionError,
            ) as e:
                error = BadRequestException(str(e))
            except ConflictImageBuilderActionError as e:
                # TODO change to ConflictException after https://github.com/aws/aws-parallelcluster/pull/2776 is merged
                error = InternalServiceException(str(e))
            except Exception as e:
                error = InternalServiceException(str(e))
            raise error

        return wrapper

    return _decorate_image_operations_api


@configure_aws_region(is_query_string_arg=False)
@convert_imagebuilder_errors()
def build_image(
    build_image_request_content,
    suppress_validators=None,
    validation_failure_level=None,
    dryrun=None,
    rollback_on_failure=None,
    client_token=None,
):
    """
    Create a custom ParallelCluster image in a given region.

    :param build_image_request_content:
    :param suppress_validators: Identifies one or more config validators to suppress.
    Format: ALL|id:$value|level:(info|error|warning)|type:$value
    :type suppress_validators: List[str]
    :param validation_failure_level: Min validation level that will cause the image creation to fail.
    Defaults to &#39;error&#39;.
    :type validation_failure_level: dict | bytes
    :param dryrun: Only perform request validation without creating any resource.
    It can be used to validate the image configuration. Response code: 200
    :type dryrun: bool
    :param rollback_on_failure: When set it automatically initiates an image stack rollback on failures.
    Defaults to true.
    :type rollback_on_failure: bool
    :param client_token: Idempotency token that can be set by the client so that retries for the same request are
    idempotent
    :type client_token: str

    :rtype: BuildImageResponseContent
    """
    if client_token:
        raise BuildImageBadRequestException(
            BuildImageBadRequestExceptionResponseContent(
                message="clientToken is currently not supported for this operation",
                configuration_validation_errors=[],
            )
        )

    rollback_on_failure = rollback_on_failure or False
    disable_rollback = not rollback_on_failure
    suppress_validators = suppress_validators or False
    validation_failure_level = validation_failure_level or FailureLevel.ERROR
    dryrun = dryrun or False

    build_image_request_content = BuildImageRequestContent.from_dict(build_image_request_content)

    try:
        image_id = build_image_request_content.id
        config = parse_config(build_image_request_content.image_configuration)
        imagebuilder = ImageBuilder(image_id=image_id, config=config)

        if dryrun:
            imagebuilder.validate_create_request(suppress_validators, validation_failure_level)
            # TODO change to DryrunOperationException after merging https://github.com/aws/aws-parallelcluster/pull/2776
            raise Exception("temp exception, throw the DryrunOperationException we throw in CreateCluster")

        imagebuilder.create(disable_rollback, suppress_validators, validation_failure_level)
        return BuildImageResponseContent(image=_imagebuilder_stack_to_image_info_summary(imagebuilder.stack))
    except BadRequestImageBuilderActionError as e:
        errors = validation_results_to_config_validation_errors(e.validation_failures)
        raise BuildImageBadRequestException(
            BuildImageBadRequestExceptionResponseContent(message=str(e), configuration_validation_errors=errors)
        )


@configure_aws_region()
@convert_imagebuilder_errors()
def delete_image(image_id, region=None, client_token=None, force=None):
    """
    Initiate the deletion of the custom ParallelCluster image.

    :param image_id: Id of the image
    :type image_id: str
    :param region: AWS Region. Defaults to the region the API is deployed to.
    :type region: str
    :param client_token: Idempotency token that can be set by the client so that retries for the same request are
    idempotent
    :type client_token: str
    :param force: Force deletion in case there are instances using the AMI or in case the AMI is shared
    :type force: bool

    :rtype: DeleteImageResponseContent
    """
    if client_token:
        raise BadRequestException("clientToken is currently not supported for this operation")

    force = force or False
    imagebuilder = ImageBuilder(image_id=image_id)
    image, stack = _get_underlying_image_or_stack(imagebuilder)

    imagebuilder.delete(force=force)

    return DeleteImageResponseContent(
        image=ImageInfoSummary(
            image_id=image_id,
            image_build_status=ImageBuildStatus.DELETE_IN_PROGRESS,
            cloudformation_stack_status=CloudFormationStatus.DELETE_IN_PROGRESS if stack else None,
            cloudformation_stack_arn=stack.id if stack else None,
            region=os_lib.environ.get("AWS_DEFAULT_REGION"),
            version=stack.version if stack else image.version,
        )
    )


def _get_underlying_image_or_stack(imagebuilder):
    image = None
    stack = None
    try:
        image = imagebuilder.image
    except NonExistingImageError:
        try:
            stack = imagebuilder.stack
        except NonExistingStackError:
            raise NotFoundException(
                f"Unable to find an image or stack for ParallelCluster image id: {imagebuilder.image_id}"
            )
    return image, stack


@configure_aws_region()
def describe_image(image_id, region=None):
    """
    Get detailed information about an existing image.

    :param image_id: Id of the image
    :type image_id: str
    :param region: AWS Region. Defaults to the region the API is deployed to.
    :type region: str

    :rtype: DescribeImageResponseContent
    """
    return DescribeImageResponseContent(
        image_configuration=ImageConfigurationStructure(s3_url="s3"),
        image_id="imageid",
        imagebuilder_image_status=ImageBuilderImageStatus.BUILDING,
        creation_time=datetime.now(),
        image_build_status=ImageBuildStatus.BUILD_FAILED,
        failure_reason=":D",
        cloudformation_stack_status=CloudFormationStatus.CREATE_COMPLETE,
        cloudformation_stack_arn="arn",
        region="region",
        version="3.0.0",
        tags=[],
    )


@configure_aws_region()
def describe_official_images(version=None, region=None, os=None, architecture=None, next_token=None):
    """
    Describe ParallelCluster AMIs.

    :param version: ParallelCluster version to retrieve AMIs for.
    :type version: str
    :param region: AWS Region. Defaults to the region the API is deployed to.
    :type region: str
    :param os: Filter by OS distribution
    :type os: str
    :param architecture: Filter by architecture
    :type architecture: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str

    :rtype: DescribeOfficialImagesResponseContent
    """
    return DescribeOfficialImagesResponseContent(items=[])


@configure_aws_region()
@convert_imagebuilder_errors()
def list_images(image_status, region=None, next_token=None):
    """
    Retrieve the list of existing custom images managed by the API. Deleted images are not showed by default.

    :param image_status: Filter by image status.
    :type image_status: dict | bytes
    :param region: List Images built into a given AWS Region. Defaults to the AWS region the API is deployed to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str

    :rtype: ListImagesResponseContent
    """
    if image_status == ImageStatusFilteringOption.AVAILABLE:
        return ListImagesResponseContent(items=_get_available_images())
    else:
        items, next_token = _get_images_in_progress(image_status, next_token)
        return ListImagesResponseContent(items=items, next_token=next_token)


def _get_available_images():
    return [_image_info_to_image_info_summary(image) for image in AWSApi.instance().ec2.get_images()]


def _get_images_in_progress(image_status, next_token):
    stacks, next_token = AWSApi.instance().cfn.get_imagebuilder_stacks(next_token=next_token)
    imagebuilder_stacks = [ImageBuilderStack(stack) for stack in stacks]
    cloudformation_states = _image_status_to_cloudformation_status(image_status)
    summaries = [
        _imagebuilder_stack_to_image_info_summary(stack)
        for stack in imagebuilder_stacks
        if stack.status in cloudformation_states
    ]
    return summaries, next_token


def _image_status_to_cloudformation_status(image_status):
    mapping = {
        ImageStatusFilteringOption.AVAILABLE: {CloudFormationStatus.CREATE_COMPLETE},
        ImageStatusFilteringOption.PENDING: {CloudFormationStatus.CREATE_IN_PROGRESS},
        ImageStatusFilteringOption.FAILED: {CloudFormationStatus.CREATE_FAILED, CloudFormationStatus.DELETE_FAILED},
    }
    return mapping.get(image_status, set())


def _imagebuilder_stack_to_image_info_summary(stack):
    return ImageInfoSummary(
        image_id=stack.pcluster_image_id,
        image_build_status=cloud_formation_status_to_image_status(stack.status),
        cloudformation_stack_status=stack.status,
        cloudformation_stack_arn=stack.id,
        region=os_lib.environ.get("AWS_DEFAULT_REGION"),
        version=stack.version,
    )


def _image_info_to_image_info_summary(image):
    return ImageInfoSummary(
        image_id=image.pcluster_image_id,
        image_build_status=ImageBuildStatus.BUILD_COMPLETE,
        region=os_lib.environ.get("AWS_DEFAULT_REGION"),
        version=image.version,
    )
