# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=W0613

from datetime import datetime

from pcluster.api.controllers.common import configure_aws_region
from pcluster.api.models import (
    BuildImageRequestContent,
    BuildImageResponseContent,
    CloudFormationStatus,
    DescribeImageResponseContent,
    DescribeOfficialImagesResponseContent,
    ImageBuilderImageStatus,
    ImageConfigurationStructure,
    ImageInfoSummary,
    ListImagesResponseContent,
)
from pcluster.api.models.delete_image_response_content import DeleteImageResponseContent
from pcluster.api.models.image_build_status import ImageBuildStatus


@configure_aws_region(is_query_string_arg=False)
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
    Format: (ALL|type:[A-Za-z0-9]+)
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
    build_image_request_content = BuildImageRequestContent.from_dict(build_image_request_content)
    return BuildImageResponseContent(
        image=ImageInfoSummary(
            image_id="image",
            image_build_status=ImageBuildStatus.BUILD_FAILED,
            cloudformation_stack_status=CloudFormationStatus.CREATE_COMPLETE,
            cloudformation_stack_arn="arn",
            region="region",
            version="3.0.0",
        )
    )


@configure_aws_region()
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
    return DeleteImageResponseContent(
        image=ImageInfoSummary(
            image_id="image",
            image_build_status=ImageBuildStatus.BUILD_FAILED,
            cloudformation_stack_status=CloudFormationStatus.CREATE_COMPLETE,
            cloudformation_stack_arn="arn",
            region="region",
            version="3.0.0",
        )
    )


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
def list_images(region=None, next_token=None, image_status=None):
    """
    Retrieve the list of existing custom images managed by the API. Deleted images are not showed by default.

    :param region: List Images built into a given AWS Region. Defaults to the AWS region the API is deployed to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str
    :param image_status: Filter by image status.
    :type image_status: list | bytes

    :rtype: ListImagesResponseContent
    """
    return ListImagesResponseContent(items=[])
