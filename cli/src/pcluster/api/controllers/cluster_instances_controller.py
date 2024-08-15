import connexion
import six
from typing import Dict
from typing import Tuple
from typing import Union

from pcluster.api.models.bad_request_exception_response_content import BadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.describe_cluster_instances_response_content import DescribeClusterInstancesResponseContent  # noqa: E501
from pcluster.api.models.internal_service_exception_response_content import InternalServiceExceptionResponseContent  # noqa: E501
from pcluster.api.models.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent  # noqa: E501
from pcluster.api.models.node_type import NodeType  # noqa: E501
from pcluster.api.models.not_found_exception_response_content import NotFoundExceptionResponseContent  # noqa: E501
from pcluster.api.models.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent  # noqa: E501
from pcluster.api import util


def delete_cluster_instances(cluster_name, region=None, force=None):  # noqa: E501
    """delete_cluster_instances

    Initiate the forced termination of all cluster compute nodes. Does not work with AWS Batch clusters. # noqa: E501

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param force: Force the deletion also when the cluster with the given name is not found. (Defaults to &#39;false&#39;.)
    :type force: bool

    :rtype: Union[None, Tuple[None, int], Tuple[None, int, Dict[str, str]]
    """
    return 'do some magic!'


def describe_cluster_instances(cluster_name, region=None, next_token=None, node_type=None, queue_name=None):  # noqa: E501
    """describe_cluster_instances

    Describe the instances belonging to a given cluster. # noqa: E501

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str
    :param node_type: Filter the instances by node type.
    :type node_type: dict | bytes
    :param queue_name: Filter the instances by queue name.
    :type queue_name: str

    :rtype: Union[DescribeClusterInstancesResponseContent, Tuple[DescribeClusterInstancesResponseContent, int], Tuple[DescribeClusterInstancesResponseContent, int, Dict[str, str]]
    """
    if connexion.request.is_json:
        node_type =  NodeType.from_dict(connexion.request.get_json())  # noqa: E501
    return 'do some magic!'
