import connexion
import six
from typing import Dict
from typing import Tuple
from typing import Union

from pcluster.api.models.bad_request_exception_response_content import BadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.cluster_status_filtering_option import ClusterStatusFilteringOption  # noqa: E501
from pcluster.api.models.conflict_exception_response_content import ConflictExceptionResponseContent  # noqa: E501
from pcluster.api.models.create_cluster_bad_request_exception_response_content import CreateClusterBadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.create_cluster_request_content import CreateClusterRequestContent  # noqa: E501
from pcluster.api.models.create_cluster_response_content import CreateClusterResponseContent  # noqa: E501
from pcluster.api.models.delete_cluster_response_content import DeleteClusterResponseContent  # noqa: E501
from pcluster.api.models.describe_cluster_response_content import DescribeClusterResponseContent  # noqa: E501
from pcluster.api.models.dryrun_operation_exception_response_content import DryrunOperationExceptionResponseContent  # noqa: E501
from pcluster.api.models.internal_service_exception_response_content import InternalServiceExceptionResponseContent  # noqa: E501
from pcluster.api.models.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent  # noqa: E501
from pcluster.api.models.list_clusters_response_content import ListClustersResponseContent  # noqa: E501
from pcluster.api.models.not_found_exception_response_content import NotFoundExceptionResponseContent  # noqa: E501
from pcluster.api.models.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent  # noqa: E501
from pcluster.api.models.update_cluster_bad_request_exception_response_content import UpdateClusterBadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.update_cluster_request_content import UpdateClusterRequestContent  # noqa: E501
from pcluster.api.models.update_cluster_response_content import UpdateClusterResponseContent  # noqa: E501
from pcluster.api.models.validation_level import ValidationLevel  # noqa: E501
from pcluster.api import util


def create_cluster(create_cluster_request_content, region=None, suppress_validators=None, validation_failure_level=None, dryrun=None, rollback_on_failure=None):  # noqa: E501
    """create_cluster

    Create a managed cluster in a given region. # noqa: E501

    :param create_cluster_request_content: 
    :type create_cluster_request_content: dict | bytes
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param suppress_validators: Identifies one or more config validators to suppress. Format: (ALL|type:[A-Za-z0-9]+)
    :type suppress_validators: List[str]
    :param validation_failure_level: Min validation level that will cause the creation to fail. (Defaults to &#39;ERROR&#39;.)
    :type validation_failure_level: dict | bytes
    :param dryrun: Only perform request validation without creating any resource. May be used to validate the cluster configuration. (Defaults to &#39;false&#39;.)
    :type dryrun: bool
    :param rollback_on_failure: When set it automatically initiates a cluster stack rollback on failures. (Defaults to &#39;true&#39;.)
    :type rollback_on_failure: bool

    :rtype: Union[CreateClusterResponseContent, Tuple[CreateClusterResponseContent, int], Tuple[CreateClusterResponseContent, int, Dict[str, str]]
    """
    if connexion.request.is_json:
        create_cluster_request_content = CreateClusterRequestContent.from_dict(connexion.request.get_json())  # noqa: E501
    if connexion.request.is_json:
        validation_failure_level =  ValidationLevel.from_dict(connexion.request.get_json())  # noqa: E501
    return 'do some magic!'


def delete_cluster(cluster_name, region=None):  # noqa: E501
    """delete_cluster

    Initiate the deletion of a cluster. # noqa: E501

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str

    :rtype: Union[DeleteClusterResponseContent, Tuple[DeleteClusterResponseContent, int], Tuple[DeleteClusterResponseContent, int, Dict[str, str]]
    """
    return 'do some magic!'


def describe_cluster(cluster_name, region=None):  # noqa: E501
    """describe_cluster

    Get detailed information about an existing cluster. # noqa: E501

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str

    :rtype: Union[DescribeClusterResponseContent, Tuple[DescribeClusterResponseContent, int], Tuple[DescribeClusterResponseContent, int, Dict[str, str]]
    """
    return 'do some magic!'


def list_clusters(region=None, next_token=None, cluster_status=None):  # noqa: E501
    """list_clusters

    Retrieve the list of existing clusters. # noqa: E501

    :param region: List clusters deployed to a given AWS Region.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str
    :param cluster_status: Filter by cluster status. (Defaults to all clusters.)
    :type cluster_status: list | bytes

    :rtype: Union[ListClustersResponseContent, Tuple[ListClustersResponseContent, int], Tuple[ListClustersResponseContent, int, Dict[str, str]]
    """
    if connexion.request.is_json:
        cluster_status = [ClusterStatusFilteringOption.from_dict(d) for d in connexion.request.get_json()]  # noqa: E501
    return 'do some magic!'


def update_cluster(update_cluster_request_content, cluster_name, suppress_validators=None, validation_failure_level=None, region=None, dryrun=None, force_update=None):  # noqa: E501
    """update_cluster

    Update a cluster managed in a given region. # noqa: E501

    :param update_cluster_request_content: 
    :type update_cluster_request_content: dict | bytes
    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param suppress_validators: Identifies one or more config validators to suppress. Format: (ALL|type:[A-Za-z0-9]+)
    :type suppress_validators: List[str]
    :param validation_failure_level: Min validation level that will cause the update to fail. (Defaults to &#39;ERROR&#39;.)
    :type validation_failure_level: dict | bytes
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param dryrun: Only perform request validation without creating any resource. May be used to validate the cluster configuration and update requirements. (Defaults to &#39;false&#39;.)
    :type dryrun: bool
    :param force_update: Force update by ignoring the update validation errors. (Defaults to &#39;false&#39;.)
    :type force_update: bool

    :rtype: Union[UpdateClusterResponseContent, Tuple[UpdateClusterResponseContent, int], Tuple[UpdateClusterResponseContent, int, Dict[str, str]]
    """
    if connexion.request.is_json:
        update_cluster_request_content = UpdateClusterRequestContent.from_dict(connexion.request.get_json())  # noqa: E501
    if connexion.request.is_json:
        validation_failure_level =  ValidationLevel.from_dict(connexion.request.get_json())  # noqa: E501
    return 'do some magic!'
