import connexion
import six
from typing import Dict
from typing import Tuple
from typing import Union

from pcluster.api.models.bad_request_exception_response_content import BadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.describe_compute_fleet_response_content import DescribeComputeFleetResponseContent  # noqa: E501
from pcluster.api.models.internal_service_exception_response_content import InternalServiceExceptionResponseContent  # noqa: E501
from pcluster.api.models.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent  # noqa: E501
from pcluster.api.models.not_found_exception_response_content import NotFoundExceptionResponseContent  # noqa: E501
from pcluster.api.models.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent  # noqa: E501
from pcluster.api.models.update_compute_fleet_request_content import UpdateComputeFleetRequestContent  # noqa: E501
from pcluster.api.models.update_compute_fleet_response_content import UpdateComputeFleetResponseContent  # noqa: E501
from pcluster.api import util


def describe_compute_fleet(cluster_name, region=None):  # noqa: E501
    """describe_compute_fleet

    Describe the status of the compute fleet. # noqa: E501

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str

    :rtype: Union[DescribeComputeFleetResponseContent, Tuple[DescribeComputeFleetResponseContent, int], Tuple[DescribeComputeFleetResponseContent, int, Dict[str, str]]
    """
    return 'do some magic!'


def update_compute_fleet(update_compute_fleet_request_content, cluster_name, region=None):  # noqa: E501
    """update_compute_fleet

    Update the status of the cluster compute fleet. # noqa: E501

    :param update_compute_fleet_request_content: 
    :type update_compute_fleet_request_content: dict | bytes
    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str

    :rtype: Union[UpdateComputeFleetResponseContent, Tuple[UpdateComputeFleetResponseContent, int], Tuple[UpdateComputeFleetResponseContent, int, Dict[str, str]]
    """
    if connexion.request.is_json:
        update_compute_fleet_request_content = UpdateComputeFleetRequestContent.from_dict(connexion.request.get_json())  # noqa: E501
    return 'do some magic!'
