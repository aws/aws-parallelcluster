# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=W0613
import logging
import os as os_lib

from pcluster.api.controllers.common import (
    configure_aws_region,
    configure_aws_region_from_config,
    convert_errors,
    get_validator_suppressors,
    http_success_status_code,
)
from pcluster.api.converters import (
    cloud_formation_status_to_image_status,
    validation_results_to_config_validation_errors,
)
from pcluster.api.errors import (
    BadRequestException,
    BuildImageBadRequestException,
    DryrunOperationException,
    NotFoundException,
)
from pcluster.api.models import (
    AmiInfo,
    BuildImageBadRequestExceptionResponseContent,
    BuildImageRequestContent,
    BuildImageResponseContent,
    CloudFormationStackStatus,
    DescribeImageResponseContent,
    Ec2AmiInfo,
    Ec2AmiInfoSummary,
    ImageConfigurationStructure,
    ImageInfoSummary,
    ImageStatusFilteringOption,
    ListImagesResponseContent,
    ListOfficialImagesResponseContent,
    Tag,
    ValidationLevel,
)
from pcluster.api.models.delete_image_response_content import DeleteImageResponseContent
from pcluster.api.models.image_build_status import ImageBuildStatus
from pcluster.api.util import assert_valid_node_js
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from pcluster.aws.ec2 import Ec2Client
from pcluster.constants import SUPPORTED_ARCHITECTURES, SUPPORTED_OSES
from pcluster.models.imagebuilder import (
    BadRequestImageBuilderActionError,
    ConfigValidationError,
    ImageBuilder,
    NonExistingImageError,
)
from pcluster.models.imagebuilder_resources import ImageBuilderStack, NonExistingStackError
from pcluster.utils import get_installed_version, to_utc_datetime
from pcluster.validators.common import FailureLevel

LOGGER = logging.getLogger(__name__)


@http_success_status_code(202)
@convert_errors()
def build_image(
    build_image_request_content,
    suppress_validators=None,
    validation_failure_level=None,
    dryrun=None,
    rollback_on_failure=None,
    region=None,
):
    """
    Create a custom ParallelCluster image in a given region.

    :param build_image_request_content:
    :param suppress_validators: Identifies one or more config validators to suppress.
    Format: (ALL|type:[A-Za-z0-9]+)
    :type suppress_validators: List[str]
    :param validation_failure_level: Min validation level that will cause the image creation to fail.
    Defaults to &#39;error&#39;.
    :type validation_failure_level: dict | bytes
    :param dryrun: Only perform request validation without creating any resource.
    It can be used to validate the image configuration. Response code: 200
    (Defaults to &#39;false&#39;.)
    :type dryrun: bool
    :param rollback_on_failure: When set, will automatically initiate an image stack rollback on failure.
    (Defaults to &#39;false&#39;.)
    :type rollback_on_failure: bool
    :param region: AWS Region that the operation corresponds to.
    :type region: str

    :rtype: BuildImageResponseContent
    """
    assert_valid_node_js()
    configure_aws_region_from_config(region, build_image_request_content["imageConfiguration"])
    rollback_on_failure = rollback_on_failure if rollback_on_failure is not None else False
    disable_rollback = not rollback_on_failure
    validation_failure_level = validation_failure_level or ValidationLevel.ERROR
    dryrun = dryrun or False

    build_image_request_content = BuildImageRequestContent.from_dict(build_image_request_content)

    try:
        image_id = build_image_request_content.image_id
        config = build_image_request_content.image_configuration

        if not config:
            LOGGER.error("Failed: configuration is required and cannot be empty")
            raise BadRequestException("configuration is required and cannot be empty")

        imagebuilder = ImageBuilder(image_id=image_id, config=config)

        if dryrun:
            imagebuilder.validate_create_request(
                validator_suppressors=get_validator_suppressors(suppress_validators),
                validation_failure_level=FailureLevel[validation_failure_level],
            )
            raise DryrunOperationException()

        suppressed_validation_failures = imagebuilder.create(
            disable_rollback=disable_rollback,
            validator_suppressors=get_validator_suppressors(suppress_validators),
            validation_failure_level=FailureLevel[validation_failure_level],
        )

        return BuildImageResponseContent(
            image=_imagebuilder_stack_to_image_info_summary(imagebuilder.stack),
            validation_messages=validation_results_to_config_validation_errors(suppressed_validation_failures) or None,
        )
    except ConfigValidationError as e:
        raise _handle_config_validation_error(e)
    except BadRequestImageBuilderActionError as e:
        errors = validation_results_to_config_validation_errors(e.validation_failures)
        raise BuildImageBadRequestException(
            BuildImageBadRequestExceptionResponseContent(message=str(e), configuration_validation_errors=errors or None)
        )


@configure_aws_region()
@http_success_status_code(202)
@convert_errors()
def delete_image(image_id, region=None, force=None):
    """
    Initiate the deletion of the custom ParallelCluster image.

    :param image_id: Id of the image
    :type image_id: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param force: Force deletion in case there are instances using the AMI or in case the AMI is shared
    (Defaults to &#39;false&#39;.)
    :type force: bool

    :rtype: DeleteImageResponseContent
    """
    force = force or False
    imagebuilder = ImageBuilder(image_id=image_id)
    image, stack = _get_underlying_image_or_stack(imagebuilder)

    imagebuilder.delete(force=force)

    return DeleteImageResponseContent(
        image=ImageInfoSummary(
            image_id=image_id,
            image_build_status=ImageBuildStatus.DELETE_IN_PROGRESS,
            cloudformation_stack_status=CloudFormationStackStatus.DELETE_IN_PROGRESS if stack else None,
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
                f"No image or stack associated with ParallelCluster image id: {imagebuilder.image_id}."
            )
    return image, stack


@configure_aws_region()
@convert_errors()
def describe_image(image_id, region=None):
    """
    Get detailed information about an existing image.

    :param image_id: Id of the image
    :type image_id: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str

    :rtype: DescribeImageResponseContent
    """
    imagebuilder = ImageBuilder(image_id=image_id)

    try:
        return _image_to_describe_image_response(imagebuilder)
    except NonExistingImageError:
        try:
            return _stack_to_describe_image_response(imagebuilder)
        except NonExistingStackError:
            raise NotFoundException("No image or stack associated with ParallelCluster image id: {}.".format(image_id))


def _presigned_config_url(imagebuilder):
    """Get the URL for the config as a pre-signed S3 URL."""
    # Do not fail request when S3 bucket is not available
    config_url = "NOT_AVAILABLE"
    try:
        config_url = imagebuilder.presigned_config_url
    except AWSClientError as e:
        LOGGER.error(e)
    return config_url


def _image_to_describe_image_response(imagebuilder):
    return DescribeImageResponseContent(
        creation_time=to_utc_datetime(imagebuilder.image.creation_date),
        image_configuration=ImageConfigurationStructure(url=_presigned_config_url(imagebuilder)),
        image_id=imagebuilder.image_id,
        image_build_status=ImageBuildStatus.BUILD_COMPLETE,
        ec2_ami_info=Ec2AmiInfo(
            ami_name=imagebuilder.image.name,
            ami_id=imagebuilder.image.id,
            state=imagebuilder.image.state.upper(),
            tags=[Tag(key=tag["Key"], value=tag["Value"]) for tag in imagebuilder.image.tags],
            architecture=imagebuilder.image.architecture,
            description=imagebuilder.image.description,
        ),
        region=os_lib.environ.get("AWS_DEFAULT_REGION"),
        version=imagebuilder.image.version,
    )


def _stack_to_describe_image_response(imagebuilder):
    imagebuilder_image_state = imagebuilder.stack.image_state or {}
    return DescribeImageResponseContent(
        image_configuration=ImageConfigurationStructure(url=_presigned_config_url(imagebuilder)),
        image_id=imagebuilder.image_id,
        image_build_status=imagebuilder.imagebuild_status,
        image_build_logs_arn=imagebuilder.stack.build_log,
        imagebuilder_image_status=imagebuilder_image_state.get("status", None),
        imagebuilder_image_status_reason=imagebuilder_image_state.get("reason", None),
        cloudformation_stack_status=imagebuilder.stack.status,
        cloudformation_stack_status_reason=imagebuilder.stack.status_reason,
        cloudformation_stack_arn=imagebuilder.stack.id,
        cloudformation_stack_creation_time=to_utc_datetime(imagebuilder.stack.creation_time),
        cloudformation_stack_tags=[Tag(key=tag["Key"], value=tag["Value"]) for tag in imagebuilder.stack.tags],
        region=os_lib.environ.get("AWS_DEFAULT_REGION"),
        version=imagebuilder.stack.version,
    )


@configure_aws_region()
@convert_errors()
def list_official_images(region=None, os=None, architecture=None):
    """
    Describe ParallelCluster AMIs.

    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param os: Filter by OS distribution (Default is to not filter.)
    :type os: str
    :param architecture: Filter by architecture (Default is to not filter.)
    :type architecture: str

    :rtype: ListOfficialImagesResponseContent
    """
    _validate_optional_filters(os, architecture)

    images = [
        _image_info_to_ami_info(image)
        for image in AWSApi.instance().ec2.get_official_images(os=os, architecture=architecture)
    ]

    return ListOfficialImagesResponseContent(images=images)


def _validate_optional_filters(os, architecture):
    error = ""
    if os is not None and os not in SUPPORTED_OSES:
        error = f"{os} is not one of {SUPPORTED_OSES}"
    if architecture is not None and architecture not in SUPPORTED_ARCHITECTURES:
        if error:
            error += "; "
        error += f"{architecture} is not one of {SUPPORTED_ARCHITECTURES}"
    if error:
        raise BadRequestException(error)


def _image_info_to_ami_info(image):
    return AmiInfo(
        ami_id=image.id,
        os=Ec2Client.extract_os_from_official_image_name(image.name),
        name=image.name,
        architecture=image.architecture,
        version=get_installed_version(),
    )


@configure_aws_region()
@convert_errors()
def list_images(image_status, region=None, next_token=None):
    """
    Retrieve the list of existing custom images.

    :param image_status: Filter by image status.
    :type image_status: dict | bytes
    :param region: List images built in a given AWS Region.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str

    :rtype: ListImagesResponseContent
    """
    if image_status == ImageStatusFilteringOption.AVAILABLE:
        return ListImagesResponseContent(images=_get_available_images())
    else:
        images, next_token = _get_images_in_progress(image_status, next_token)
        return ListImagesResponseContent(images=images, next_token=next_token)


def _handle_config_validation_error(e: ConfigValidationError) -> BuildImageBadRequestException:
    config_validation_messages = validation_results_to_config_validation_errors(e.validation_failures) or None
    return BuildImageBadRequestException(
        BuildImageBadRequestExceptionResponseContent(
            configuration_validation_errors=config_validation_messages, message=str(e)
        )
    )


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
        ImageStatusFilteringOption.AVAILABLE: {CloudFormationStackStatus.CREATE_COMPLETE},
        ImageStatusFilteringOption.PENDING: {CloudFormationStackStatus.CREATE_IN_PROGRESS},
        ImageStatusFilteringOption.FAILED: {
            CloudFormationStackStatus.CREATE_FAILED,
            CloudFormationStackStatus.DELETE_FAILED,
            CloudFormationStackStatus.ROLLBACK_FAILED,
            CloudFormationStackStatus.ROLLBACK_COMPLETE,
            CloudFormationStackStatus.ROLLBACK_IN_PROGRESS,
        },
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
        ec2_ami_info=Ec2AmiInfoSummary(ami_id=image.id),
        region=os_lib.environ.get("AWS_DEFAULT_REGION"),
        version=image.version,
    )
