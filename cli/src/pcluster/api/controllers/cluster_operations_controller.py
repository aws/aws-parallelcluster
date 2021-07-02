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
    convert_errors,
    get_validator_suppressors,
    http_success_status_code,
    read_config,
)
from pcluster.api.converters import (
    cloud_formation_status_to_cluster_status,
    validation_results_to_config_validation_errors,
)
from pcluster.api.errors import (
    BadRequestException,
    CreateClusterBadRequestException,
    DryrunOperationException,
    InternalServiceException,
    NotFoundException,
    UpdateClusterBadRequestException,
)
from pcluster.api.models import (
    Change,
    CloudFormationStatus,
    ClusterConfigurationStructure,
    ClusterInfoSummary,
    CreateClusterBadRequestExceptionResponseContent,
    CreateClusterRequestContent,
    CreateClusterResponseContent,
    DeleteClusterResponseContent,
    DescribeClusterResponseContent,
    EC2Instance,
    InstanceState,
    ListClustersResponseContent,
    Tag,
    UpdateClusterBadRequestExceptionResponseContent,
    UpdateClusterRequestContent,
    UpdateClusterResponseContent,
    UpdateError,
    ValidationLevel,
)
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import StackNotFoundError
from pcluster.cli_commands.compute_fleet_status_manager import ComputeFleetStatus
from pcluster.config.update_policy import UpdatePolicy
from pcluster.models.cluster import (
    Cluster,
    ClusterActionError,
    ClusterUpdateError,
    ConfigValidationError,
    NotFoundClusterActionError,
)
from pcluster.models.cluster_resources import ClusterStack
from pcluster.utils import get_installed_version
from pcluster.validators.common import FailureLevel

LOGGER = logging.getLogger(__name__)


@configure_aws_region(is_query_string_arg=False)
@convert_errors()
@http_success_status_code(202)
def create_cluster(
    create_cluster_request_content: Dict,
    suppress_validators: List[str] = None,
    validation_failure_level: str = None,
    dryrun: bool = None,
    rollback_on_failure: bool = None,
) -> CreateClusterResponseContent:
    """
    Create a ParallelCluster managed cluster in a given region.

    :param create_cluster_request_content:
    :param suppress_validators: Identifies one or more config validators to suppress.
    Format: (ALL|type:[A-Za-z0-9]+)
    :param validation_failure_level: Min validation level that will cause the cluster creation to fail.
    Defaults to &#39;ERROR&#39;.
    :param dryrun: Only perform request validation without creating any resource. It can be used to validate the cluster
    configuration. Response code: 200
    :param rollback_on_failure: When set it automatically initiates a cluster stack rollback on failures.
    Defaults to true.
    """
    # Set defaults
    rollback_on_failure = rollback_on_failure or True
    validation_failure_level = validation_failure_level or ValidationLevel.ERROR
    dryrun = dryrun or False
    create_cluster_request_content = CreateClusterRequestContent.from_dict(create_cluster_request_content)
    cluster_config = read_config(create_cluster_request_content.cluster_configuration)

    try:
        cluster = Cluster(create_cluster_request_content.name, cluster_config)

        if dryrun:
            cluster.validate_create_request(
                get_validator_suppressors(suppress_validators), FailureLevel[validation_failure_level]
            )
            raise DryrunOperationException()

        stack_id, ignored_validation_failures = cluster.create(
            disable_rollback=not rollback_on_failure,
            validator_suppressors=get_validator_suppressors(suppress_validators),
            validation_failure_level=FailureLevel[validation_failure_level],
        )

        return CreateClusterResponseContent(
            ClusterInfoSummary(
                cluster_name=create_cluster_request_content.name,
                cloudformation_stack_status=CloudFormationStatus.CREATE_IN_PROGRESS,
                cloudformation_stack_arn=stack_id,
                region=os.environ.get("AWS_DEFAULT_REGION"),
                version=get_installed_version(),
                cluster_status=cloud_formation_status_to_cluster_status(CloudFormationStatus.CREATE_IN_PROGRESS),
            ),
            validation_messages=validation_results_to_config_validation_errors(ignored_validation_failures),
        )
    except ConfigValidationError as e:
        raise _handle_config_validation_error(e)


@configure_aws_region()
@convert_errors()
@http_success_status_code(202)
def delete_cluster(cluster_name, region=None):
    """
    Initiate the deletion of a cluster.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region. Defaults to the region the API is deployed to.
    :type region: str

    :rtype: DeleteClusterResponseContent
    """
    try:
        cluster = Cluster(cluster_name)

        if not check_cluster_version(cluster):
            raise BadRequestException(
                f"cluster '{cluster_name}' belongs to an incompatible ParallelCluster major version."
            )

        if not cluster.status == CloudFormationStatus.DELETE_IN_PROGRESS:
            # TODO: remove keep_logs logic from delete
            cluster.delete(keep_logs=False)

        return DeleteClusterResponseContent(
            cluster=ClusterInfoSummary(
                cluster_name=cluster_name,
                cloudformation_stack_status=CloudFormationStatus.DELETE_IN_PROGRESS,
                cloudformation_stack_arn=cluster.stack.id,
                region=os.environ.get("AWS_DEFAULT_REGION"),
                version=cluster.stack.version,
                cluster_status=cloud_formation_status_to_cluster_status(CloudFormationStatus.DELETE_IN_PROGRESS),
            )
        )
    except StackNotFoundError:
        raise NotFoundException(
            f"cluster '{cluster_name}' does not exist or belongs to an incompatible ParallelCluster major version. "
            "In case you have running instances belonging to a deleted cluster please use the DeleteClusterInstances "
            "API."
        )


@configure_aws_region()
def describe_cluster(cluster_name, region=None):
    """
    Get detailed information about an existing cluster.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region. Defaults to the region the API is deployed to.
    :type region: str

    :rtype: DescribeClusterResponseContent
    """
    try:
        cluster = Cluster(cluster_name)
        cfn_stack = cluster.stack
    except StackNotFoundError:
        raise NotFoundException(
            f"cluster '{cluster_name}' does not exist or belongs to an incompatible ParallelCluster major version."
        )

    if not check_cluster_version(cluster):
        raise BadRequestException(f"cluster '{cluster_name}' belongs to an incompatible ParallelCluster major version.")

    fleet_status = cluster.compute_fleet_status
    if fleet_status == ComputeFleetStatus.UNKNOWN:
        raise InternalServiceException("could not retrieve compute fleet status.")

    config_url = "NOT_AVAILABLE"
    try:
        config_url = cluster.config_presigned_url
    except ClusterActionError as e:
        # Do not fail request when S3 bucket is not available
        LOGGER.error(e)

    response = DescribeClusterResponseContent(
        creation_time=cfn_stack.creation_time,
        version=cfn_stack.version,
        cluster_configuration=ClusterConfigurationStructure(s3_url=config_url),
        tags=[Tag(value=tag.get("Value"), key=tag.get("Key")) for tag in cfn_stack.tags],
        cloud_formation_status=cfn_stack.status,
        cluster_name=cluster_name,
        compute_fleet_status=fleet_status.value,
        cloudformation_stack_arn=cfn_stack.id,
        last_updated_time=cfn_stack.last_updated_time,
        region=os.environ.get("AWS_DEFAULT_REGION"),
        cluster_status=cloud_formation_status_to_cluster_status(cfn_stack.status),
    )

    try:
        head_node = cluster.head_node_instance
        response.headnode = EC2Instance(
            instance_id=head_node.id,
            launch_time=head_node.launch_time,
            public_ip_address=head_node.public_ip,
            instance_type=head_node.instance_type,
            state=InstanceState.from_dict(head_node.state),
            private_ip_address=head_node.private_ip,
        )
    except ClusterActionError as e:
        # This should not be treated as a failure cause head node might not be running in some cases
        LOGGER.info(e)

    return response


@configure_aws_region()
def list_clusters(region=None, next_token=None, cluster_status=None):
    """
    Retrieve the list of existing clusters managed by the API. Deleted clusters are not listed by default.

    :param region: List clusters deployed to a given AWS Region. Defaults to the AWS region the API is deployed to.
    :type region: str
    :param next_token: Token to use for paginated requests.
    :type next_token: str
    :param cluster_status: Filter by cluster status.
    :type cluster_status: list | bytes

    :rtype: ListClustersResponseContent
    """
    stacks, next_token = AWSApi.instance().cfn.list_pcluster_stacks(next_token=next_token)
    stacks = [ClusterStack(stack) for stack in stacks]

    cluster_info_list = []
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
            )
            cluster_info_list.append(cluster_info)

    return ListClustersResponseContent(items=cluster_info_list, next_token=next_token)


@configure_aws_region()
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
    Update cluster.

    :param update_cluster_request_content:
    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param suppress_validators: Identifies one or more config validators to suppress.
    Format: (ALL|type:[A-Za-z0-9]+)
    :type suppress_validators: List[str]
    :param validation_failure_level: Min validation level that will cause the update to fail.
    Defaults to &#39;error&#39;.
    :type validation_failure_level: dict | bytes
    :param region: AWS Region. Defaults to the region the API is deployed to.
    :type region: str
    :param dryrun: Only perform request validation without creating any resource.
    It can be used to validate the cluster configuration and update requirements. Response code: 200
    :type dryrun: bool
    :param force_update: Force update by ignoring the update validation errors.
    :type force_update: bool

    :rtype: UpdateClusterResponseContent
    """
    # Set defaults
    validation_failure_level = validation_failure_level or ValidationLevel.ERROR
    dryrun = dryrun or False
    force_update = force_update or False
    update_cluster_request_content = UpdateClusterRequestContent.from_dict(update_cluster_request_content)
    cluster_config = read_config(update_cluster_request_content.cluster_configuration)

    try:
        cluster = Cluster(cluster_name)
        if not check_cluster_version(cluster, exact_match=True):
            raise BadRequestException(
                f"the update can be performed only with the same ParallelCluster version ({cluster.stack.version}) "
                "used to create the cluster."
            )

        if dryrun:
            cluster.validate_update_request(
                target_source_config=cluster_config,
                force=force_update,
                validator_suppressors=get_validator_suppressors(suppress_validators),
                validation_failure_level=FailureLevel[validation_failure_level],
            )
            raise DryrunOperationException()

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
                cloudformation_stack_status=CloudFormationStatus.UPDATE_IN_PROGRESS,
                cloudformation_stack_arn=cluster.stack.id,
                region=os.environ.get("AWS_DEFAULT_REGION"),
                version=cluster.stack.version,
                cluster_status=cloud_formation_status_to_cluster_status(CloudFormationStatus.UPDATE_IN_PROGRESS),
            ),
            validation_messages=validation_results_to_config_validation_errors(ignored_validation_failures),
            change_set=change_set,
        )
    except ConfigValidationError as e:
        raise _handle_config_validation_error(e)
    except ClusterUpdateError as e:
        raise _handle_cluster_update_error(e)
    except (NotFoundClusterActionError, StackNotFoundError):
        raise NotFoundException(
            f"cluster '{cluster_name}' does not exist or belongs to an incompatible ParallelCluster major version."
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
            message=str(e), change_set=change_set, update_validation_errors=errors
        )
    )


def _handle_config_validation_error(e: ConfigValidationError) -> CreateClusterBadRequestException:
    config_validation_messages = validation_results_to_config_validation_errors(e.validation_failures)
    return CreateClusterBadRequestException(
        CreateClusterBadRequestExceptionResponseContent(
            configuration_validation_errors=config_validation_messages, message="Invalid cluster configuration"
        )
    )


def _analyze_changes(changes):
    if changes is None or len(changes) <= 1:
        return [], []

    change_set = []
    errors = []
    key_indexes = {key: index for index, key in enumerate(changes[0])}

    for row in changes[1:]:
        parameter = _get_yaml_path(row[key_indexes["param_path"]], row[key_indexes["parameter"]])
        new_value = row[key_indexes["new value"]]
        old_value = row[key_indexes["old value"]]
        check_result = row[key_indexes["check"]]
        message = _create_message(row[key_indexes["reason"]], row[key_indexes["action_needed"]])
        if check_result != UpdatePolicy.CheckResult.SUCCEEDED:
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


def _get_yaml_path(path, parameter):
    """Compose the parameter path following the YAML Path standard.

    Standard: https://github.com/wwkimball/yamlpath/wiki/Segments-of-a-YAML-Path#yaml-path-standard
    """
    yaml_path = []
    if path:
        yaml_path.extend(path)
    if parameter:
        yaml_path.append(parameter)
    return ".".join(yaml_path)
