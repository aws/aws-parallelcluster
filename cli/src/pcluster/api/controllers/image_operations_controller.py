import connexion
import six
from typing import Dict
from typing import Tuple
from typing import Union

from pcluster.api.models.bad_request_exception_response_content import BadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.build_image_bad_request_exception_response_content import BuildImageBadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.build_image_request_content import BuildImageRequestContent  # noqa: E501
from pcluster.api.models.build_image_response_content import BuildImageResponseContent  # noqa: E501
from pcluster.api.models.conflict_exception_response_content import ConflictExceptionResponseContent  # noqa: E501
from pcluster.api.models.delete_image_response_content import DeleteImageResponseContent  # noqa: E501
from pcluster.api.models.describe_image_response_content import DescribeImageResponseContent  # noqa: E501
from pcluster.api.models.dryrun_operation_exception_response_content import DryrunOperationExceptionResponseContent  # noqa: E501
from pcluster.api.models.image_status_filtering_option import ImageStatusFilteringOption  # noqa: E501
from pcluster.api.models.internal_service_exception_response_content import InternalServiceExceptionResponseContent  # noqa: E501
from pcluster.api.models.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent  # noqa: E501
from pcluster.api.models.list_images_response_content import ListImagesResponseContent  # noqa: E501
from pcluster.api.models.list_official_images_response_content import ListOfficialImagesResponseContent  # noqa: E501
from pcluster.api.models.not_found_exception_response_content import NotFoundExceptionResponseContent  # noqa: E501
from pcluster.api.models.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent  # noqa: E501
from pcluster.api.models.validation_level import ValidationLevel  # noqa: E501
from pcluster.api import util


def build_image(build_image_request_content, suppress_validators=None, validation_failure_level=None, dryrun=None, rollback_on_failure=None, region=None):  # noqa: E501
    """build_image

    Create a custom ParallelCluster image in a given region. # noqa: E501

    :param build_image_request_content: 
    :type build_image_request_content: dict | bytes
    :param suppress_validators: Identifies one or more config validators to suppress. Format: (ALL|type:[A-Za-z0-9]+)
    :type suppress_validators: List[str]
    :param validation_failure_level: Min validation level that will cause the creation to fail. (Defaults to &#39;ERROR&#39;.)
    :type validation_failure_level: dict | bytes
    :param dryrun: Only perform request validation without creating any resource. It can be used to validate the image configuration. (Defaults to &#39;false&#39;.)
    :type dryrun: bool
    :param rollback_on_failure: When set, will automatically initiate an image stack rollback on failure. (Defaults to &#39;false&#39;.)
    :type rollback_on_failure: bool
    :param region: AWS Region that the operation corresponds to.
    :type region: str

    :rtype: Union[BuildImageResponseContent, Tuple[BuildImageResponseContent, int], Tuple[BuildImageResponseContent, int, Dict[str, str]]
    """
    if connexion.request.is_json:
        build_image_request_content = BuildImageRequestContent.from_dict(connexion.request.get_json())  # noqa: E501
    if connexion.request.is_json:
        validation_failure_level =  ValidationLevel.from_dict(connexion.request.get_json())  # noqa: E501
    return 'do some magic!'


def delete_image(image_id, region=None, force=None):  # noqa: E501
    """delete_image

    Initiate the deletion of the custom ParallelCluster image. # noqa: E501

    :param image_id: Id of the image.
    :type image_id: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param force: Force deletion in case there are instances using the AMI or in case the AMI is shared. (Defaults to &#39;false&#39;.)
    :type force: bool

    :rtype: Union[DeleteImageResponseContent, Tuple[DeleteImageResponseContent, int], Tuple[DeleteImageResponseContent, int, Dict[str, str]]
    """
    return 'do some magic!'


def describe_image(image_id, region=None):  # noqa: E501
    """describe_image

    Get detailed information about an existing image. # noqa: E501

    :param image_id: Id of the image.
    :type image_id: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str

    :rtype: Union[DescribeImageResponseContent, Tuple[DescribeImageResponseContent, int], Tuple[DescribeImageResponseContent, int, Dict[str, str]]
    """
    return 'do some magic!'


def list_images(image_status, region=None, next_token=None):  # noqa: E501
    """list_images

    Retrieve the list of existing custom images. # noqa: E501

    :param image_status: Filter images by the status provided.
    :type image_status: dict | bytes
    :param region: List images built in a given AWS Region.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str

    :rtype: Union[ListImagesResponseContent, Tuple[ListImagesResponseContent, int], Tuple[ListImagesResponseContent, int, Dict[str, str]]
    """
    if connexion.request.is_json:
        image_status =  ImageStatusFilteringOption.from_dict(connexion.request.get_json())  # noqa: E501
    return 'do some magic!'


def list_official_images(region=None, os=None, architecture=None):  # noqa: E501
    """list_official_images

    List Official ParallelCluster AMIs. # noqa: E501

    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param os: Filter by OS distribution (Default is to not filter.)
    :type os: str
    :param architecture: Filter by architecture (Default is to not filter.)
    :type architecture: str

    :rtype: Union[ListOfficialImagesResponseContent, Tuple[ListOfficialImagesResponseContent, int], Tuple[ListOfficialImagesResponseContent, int, Dict[str, str]]
    """
    return 'do some magic!'
