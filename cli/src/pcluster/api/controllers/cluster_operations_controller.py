# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=W0613
import logging
import os
from typing import Dict, List

from pcluster.api.controllers.common import (
    check_cluster_version,
    configure_aws_region,
    configure_aws_region_from_config,
    convert_errors,
    get_validator_suppressors,
    http_success_status_code,
    validate_cluster,
)
from pcluster.api.converters import (
    cloud_formation_status_to_cluster_status,
    validation_results_to_config_validation_errors,
)
from pcluster.api.errors import (
    BadRequestException,
    CreateClusterBadRequestException,
    DryrunOperationException,
    NotFoundException,
    UpdateClusterBadRequestException,
)
from pcluster.api.models import (
    Change,
    CloudFormationStackStatus,
    ClusterConfigurationStructure,
    ClusterInfoSummary,
    ClusterStatus,
    CreateClusterBadRequestExceptionResponseContent,
    CreateClusterRequestContent,
    CreateClusterResponseContent,
    DeleteClusterResponseContent,
    DescribeClusterResponseContent,
    EC2Instance,
    Failure,
    InstanceState,
    ListClustersResponseContent,
    LoginNodesPool,
    LoginNodesState,
    Scheduler,
    Tag,
    UpdateClusterBadRequestExceptionResponseContent,
    UpdateClusterRequestContent,
    UpdateClusterResponseContent,
    UpdateError,
    ValidationLevel,
)
from pcluster.api.util import assert_valid_node_js
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import StackNotFoundError
from pcluster.config.config_patch import ConfigPatch
from pcluster.config.update_policy import UpdatePolicy
from pcluster.models.cluster import (
    Cluster,
    ClusterActionError,
    ClusterUpdateError,
    ConfigValidationError,
    NotFoundClusterActionError,
)
from pcluster.models.cluster_resources import ClusterStack
from pcluster.models.login_nodes_status import LoginNodesPoolState
from pcluster.utils import get_installed_version, to_utc_datetime
from pcluster.validators.common import FailureLevel

LOGGER = logging.getLogger(__name__)


@convert_errors()
@http_success_status_code(202)
def create_cluster(
    create_cluster_request_content: Dict,
    region: str = None,
    suppress_validators: List[str] = None,
    validation_failure_level: str = None,
    dryrun: bool = None,
    rollback_on_failure: bool = None,
) -> CreateClusterResponseContent:
    """
    Create a managed cluster in a given region.

    :param create_cluster_request_content:
    :type create_cluster_request_content: dict | bytes
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param suppress_validators: Identifies one or more config validators to suppress.
    Format: (ALL|type:[A-Za-z0-9]+)
    :param validation_failure_level: Min validation level that will cause the cluster creation to fail.
    (Defaults to &#39;ERROR&#39;.)
    :param dryrun: Only perform request validation without creating any resource. May be used to validate the cluster
    configuration. (Defaults to &#39;false&#39;.)
    :type dryrun: bool
    :param rollback_on_failure: When set it automatically initiates a cluster stack rollback on failures.
    (Defaults to &#39;true&#39;.)
    :type rollback_on_failure: bool
    """
    assert_valid_node_js()
    # Set defaults
    configure_aws_region_from_config(region, create_cluster_request_content["clusterConfiguration"])
    rollback_on_failure = rollback_on_failure in {True, None}
    validation_failure_level = validation_failure_level or ValidationLevel.ERROR
    dryrun = dryrun is True

    create_cluster_request_content = CreateClusterRequestContent.from_dict(create_cluster_request_content)
    cluster_config = create_cluster_request_content.cluster_configuration

    if not cluster_config:
        LOGGER.error("Failed: configuration is required and cannot be empty")
        raise BadRequestException("configuration is required and cannot be empty")

    try:
        cluster = Cluster(create_cluster_request_content.cluster_name, cluster_config)

        if dryrun:
            ignored_validation_failures = cluster.validate_create_request(
                get_validator_suppressors(suppress_validators), FailureLevel[validation_failure_level]
            )
            validation_messages = validation_results_to_config_validation_errors(ignored_validation_failures)
            raise DryrunOperationException(validation_messages=validation_messages or None)

        stack_id, ignored_validation_failures = cluster.create(
            disable_rollback=not rollback_on_failure,
            validator_suppressors=get_validator_suppressors(suppress_validators),
            validation_failure_level=FailureLevel[validation_failure_level],
        )

        return CreateClusterResponseContent(
            ClusterInfoSummary(
                cluster_name=create_cluster_request_content.cluster_name,
                cloudformation_stack_status=CloudFormationStackStatus.CREATE_IN_PROGRESS,
                cloudformation_stack_arn=stack_id,
                region=os.environ.get("AWS_DEFAULT_REGION"),
                version=get_installed_version(),
                cluster_status=cloud_formation_status_to_cluster_status(CloudFormationStackStatus.CREATE_IN_PROGRESS),
                scheduler=Scheduler(type=cluster.config.scheduling.scheduler),
            ),
            validation_messages=validation_results_to_config_validation_errors(ignored_validation_failures) or None,
        )
    except ConfigValidationError as e:
        config_validation_messages = validation_results_to_config_validation_errors(e.validation_failures) or None
        raise CreateClusterBadRequestException(
            CreateClusterBadRequestExceptionResponseContent(
                configuration_validation_errors=config_validation_messages, message=str(e)
            )
        )


@configure_aws_region()
@convert_errors()
@http_success_status_code(202)
def delete_cluster(cluster_name, region=None):
    """
    Initiate the deletion of a cluster.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str

    :rtype: DeleteClusterResponseContent
    """
    try:
        cluster = Cluster(cluster_name)
        if not check_cluster_version(cluster):
            raise BadRequestException(
                f"Cluster '{cluster_name}' belongs to an incompatible ParallelCluster major version."
            )

        if not cluster.status == CloudFormationStackStatus.DELETE_IN_PROGRESS:
            # TODO: remove keep_logs logic from delete
            cluster.delete(keep_logs=False)

        return DeleteClusterResponseContent(
            cluster=ClusterInfoSummary(
                cluster_name=cluster_name,
                cloudformation_stack_status=CloudFormationStackStatus.DELETE_IN_PROGRESS,
                cloudformation_stack_arn=cluster.stack.id,
                region=os.environ.get("AWS_DEFAULT_REGION"),
                version=cluster.stack.version,
                cluster_status=cloud_formation_status_to_cluster_status(CloudFormationStackStatus.DELETE_IN_PROGRESS),
                scheduler=Scheduler(type=cluster.stack.scheduler),
            )
        )
    except StackNotFoundError:
        raise NotFoundException(
            f"Cluster '{cluster_name}' does not exist or belongs to an incompatible ParallelCluster major version. "
            "In case you have running instances belonging to a deleted cluster please use the DeleteClusterInstances "
            "API."
        )


@configure_aws_region()
@convert_errors()
def describe_cluster(cluster_name, region=None):
    """
    Get detailed information about an existing cluster.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region that the operation corresponds to.
    :type region: str

    :rtype: DescribeClusterResponseContent
    """
    cluster = Cluster(cluster_name)
    validate_cluster(cluster)
    cfn_stack = cluster.stack

    fleet_status = cluster.compute_fleet_status

    config_url = "NOT_AVAILABLE"
    try:
        config_url = cluster.config_presigned_url
    except ClusterActionError as e:
        # Do not fail request when S3 bucket is not available
        LOGGER.error(e)

    cluster_status = cloud_formation_status_to_cluster_status(cfn_stack.status)
    response = DescribeClusterResponseContent(
        creation_time=to_utc_datetime(cfn_stack.creation_time),
        version=cfn_stack.version,
        cluster_configuration=ClusterConfigurationStructure(url=config_url),
        tags=[Tag(value=tag.get("Value"), key=tag.get("Key")) for tag in cfn_stack.tags],
        cloud_formation_stack_status=cfn_stack.status,
        cluster_name=cluster_name,
        compute_fleet_status=fleet_status.value,
        cloudformation_stack_arn=cfn_stack.id,
        last_updated_time=to_utc_datetime(cfn_stack.last_updated_time),
        region=os.environ.get("AWS_DEFAULT_REGION"),
        cluster_status=cluster_status,
        scheduler=Scheduler(type=cluster.stack.scheduler),
        failures=_get_creation_failures(cluster_status, cfn_stack),
    )

    try:
        head_node = cluster.head_node_instance
        response.head_node = EC2Instance(
            instance_id=head_node.id,
            launch_time=to_utc_datetime(head_node.launch_time),
            public_ip_address=head_node.public_ip,
            instance_type=head_node.instance_type,
            state=InstanceState.from_dict(head_node.state),
            private_ip_address=head_node.private_ip,
        )
        login_nodes = _get_login_nodes(cluster)
        if login_nodes:
            response.login_nodes = login_nodes
    except ClusterActionError as e:
        # This should not be treated as a failure cause head node and login node might not be running in some cases.
        # e.g. when the cluster is in DELETE_IN_PROGRESS
        LOGGER.info(e)

    return response


def _get_login_nodes(cluster):
    login_nodes_status = cluster.login_nodes_status
    if login_nodes_status.get_login_nodes_pool_available():
        status = LoginNodesState.FAILED
        if login_nodes_status.get_status() == LoginNodesPoolState.ACTIVE:
            status = LoginNodesState.ACTIVE
        elif login_nodes_status.get_status() == LoginNodesPoolState.PENDING:
            status = LoginNodesState.PENDING
        login_nodes = LoginNodesPool(status=status)
        login_nodes.address = login_nodes_status.get_address()
        login_nodes.scheme = login_nodes_status.get_scheme()
        login_nodes.healthy_nodes = login_nodes_status.get_healthy_nodes()
        login_nodes.unhealthy_nodes = login_nodes_status.get_unhealthy_nodes()
        return login_nodes
    return None


@configure_aws_region()
@convert_errors()
def list_clusters(region=None, next_token=None, cluster_status=None):
    """
    Retrieve the list of existing clusters managed by the API. Deleted clusters are not listed by default.

    :param region: List clusters deployed to a given AWS Region.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str
    :param cluster_status: Filter by cluster status. (Defaults to all clusters.)
    :type cluster_status: list | bytes

    :rtype: ListClustersResponseContent
    """
    stacks, next_token = AWSApi.instance().cfn.list_pcluster_stacks(next_token=next_token)
    stacks = [ClusterStack(stack) for stack in stacks]

    clusters = []
    for stack in stacks:
        current_cluster_status = cloud_formation_status_to_cluster_status(stack.status)
        if not cluster_status or current_cluster_status in cluster_status:
            cluster_info = ClusterInfoSummary(
                cluster_name=stack.cluster_name,
                cloudformation_stack_status=stack.status,
                cloudformation_stack_arn=stack.id,
                region=os.environ.get("AWS_DEFAULT_REGION"),
                version=stack.version,
                cluster_status=current_cluster_status,
                scheduler=Scheduler(type=stack.scheduler),
            )
            clusters.append(cluster_info)

    return ListClustersResponseContent(clusters=clusters, next_token=next_token)


@convert_errors()
@http_success_status_code(202)
def update_cluster(
    update_cluster_request_content: Dict,
    cluster_name,
    suppress_validators=None,
    validation_failure_level=None,
    region=None,
    dryrun=None,
    force_update=None,
):
    """
    Update a cluster managed in a given region.

    :param update_cluster_request_content:
    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param suppress_validators: Identifies one or more config validators to suppress.
    Format: (ALL|type:[A-Za-z0-9]+)
    :type suppress_validators: List[str]
    :param validation_failure_level: Min validation level that will cause the update to fail.
    (Defaults to &#39;error&#39;.)
    :type validation_failure_level: dict | bytes
    :param region: AWS Region that the operation corresponds to.
    :type region: str
    :param dryrun: Only perform request validation without creating any resource.
    May be used to validate the cluster configuration and update requirements. Response code: 200
    :type dryrun: bool
    :param force_update: Force update by ignoring the update validation errors.
    (Defaults to &#39;false&#39;.)
    :type force_update: bool

    :rtype: UpdateClusterResponseContent
    """
    assert_valid_node_js()
    # Set defaults
    configure_aws_region_from_config(region, update_cluster_request_content["clusterConfiguration"])
    validation_failure_level = validation_failure_level or ValidationLevel.ERROR
    dryrun = dryrun is True
    force_update = force_update is True
    update_cluster_request_content = UpdateClusterRequestContent.from_dict(update_cluster_request_content)
    cluster_config = update_cluster_request_content.cluster_configuration

    if not cluster_config:
        LOGGER.error("Failed: configuration is required and cannot be empty")
        raise BadRequestException("configuration is required and cannot be empty")

    try:
        cluster = Cluster(cluster_name)
        if not check_cluster_version(cluster, exact_match=True):
            raise BadRequestException(
                f"the update can be performed only with the same ParallelCluster version ({cluster.stack.version}) "
                "used to create the cluster."
            )

        if dryrun:
            _, changes, ignored_validation_failures = cluster.validate_update_request(
                target_source_config=cluster_config,
                force=force_update,
                validator_suppressors=get_validator_suppressors(suppress_validators),
                validation_failure_level=FailureLevel[validation_failure_level],
            )
            change_set, _ = _analyze_changes(changes)
            validation_messages = validation_results_to_config_validation_errors(ignored_validation_failures)
            raise DryrunOperationException(change_set=change_set, validation_messages=validation_messages or None)

        changes, ignored_validation_failures = cluster.update(
            target_source_config=cluster_config,
            validator_suppressors=get_validator_suppressors(suppress_validators),
            validation_failure_level=FailureLevel[validation_failure_level],
            force=force_update,
        )

        change_set, _ = _analyze_changes(changes)
        return UpdateClusterResponseContent(
            cluster=ClusterInfoSummary(
                cluster_name=cluster_name,
                cloudformation_stack_status=CloudFormationStackStatus.UPDATE_IN_PROGRESS,
                cloudformation_stack_arn=cluster.stack.id,
                region=os.environ.get("AWS_DEFAULT_REGION"),
                version=cluster.stack.version,
                cluster_status=cloud_formation_status_to_cluster_status(CloudFormationStackStatus.UPDATE_IN_PROGRESS),
                scheduler=Scheduler(type=cluster.stack.scheduler),
            ),
            validation_messages=validation_results_to_config_validation_errors(ignored_validation_failures) or None,
            change_set=change_set,
        )
    except ConfigValidationError as e:
        config_validation_messages = validation_results_to_config_validation_errors(e.validation_failures) or None
        raise UpdateClusterBadRequestException(
            UpdateClusterBadRequestExceptionResponseContent(
                configuration_validation_errors=config_validation_messages, message=str(e)
            )
        )
    except ClusterUpdateError as e:
        raise _handle_cluster_update_error(e)
    except (NotFoundClusterActionError, StackNotFoundError):
        raise NotFoundException(
            f"Cluster '{cluster_name}' does not exist or belongs to an incompatible ParallelCluster major version."
        )


def _handle_cluster_update_error(e):
    """Create an UpdateClusterBadRequestExceptionResponseContent in case of failure during patch validation.

    Note that patch validation is carried out once we have successfully validated the configuration. For this reason, we
    want to avoid adding the suppressed configuration validation errors (which we attach to the response in case of a
    successful update) as we do not want to confuse the customer by showing them errors they suppressed, which did not
    cause the BadRequest exception.
    """
    change_set, errors = _analyze_changes(e.update_changes)
    return UpdateClusterBadRequestException(
        UpdateClusterBadRequestExceptionResponseContent(
            message=str(e), change_set=change_set, update_validation_errors=errors or None
        )
    )


def _cluster_update_change_succeded(check_result):
    """Describe if check_result represents successful individual change within a larger cluster update."""
    return check_result == UpdatePolicy.CheckResult.SUCCEEDED


def _analyze_changes(changes):
    if changes is None or len(changes) <= 1:
        return [], []

    change_set = []
    errors = []
    key_indexes = {key: index for index, key in enumerate(changes[0])}

    for row in changes[1:]:
        parameter = ConfigPatch.build_config_param_path(row[key_indexes["param_path"]], row[key_indexes["parameter"]])
        new_value = row[key_indexes["new value"]] if not row[key_indexes["new value"]] is None else "-"
        old_value = row[key_indexes["old value"]] if not row[key_indexes["old value"]] is None else "-"
        check_result = row[key_indexes["check"]]
        message = _create_message(row[key_indexes["reason"]], row[key_indexes["action_needed"]])
        if not _cluster_update_change_succeded(check_result):
            errors.append(
                UpdateError(parameter=parameter, requested_value=new_value, message=message, current_value=old_value)
            )
        change_set.append(Change(parameter=parameter, requested_value=new_value, current_value=old_value))
    return change_set, errors


def _create_message(failure_reason, action_needed):
    message = None
    if failure_reason:
        message = failure_reason
    if action_needed:
        message = f"{message}. {action_needed}" if message else action_needed
    return message or "Error during update"


def _get_creation_failures(cluster_status, cfn_stack):
    """Get a list of Failure objects containing failure code and reason when cluster creation failed."""
    if cluster_status != ClusterStatus.CREATE_FAILED:
        return None
    failure_code, failure_reason = cfn_stack.get_cluster_creation_failure()
    return [Failure(failure_code=failure_code, failure_reason=failure_reason)]
