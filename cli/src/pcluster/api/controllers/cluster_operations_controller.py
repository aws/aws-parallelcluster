# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=W0613
import base64
import logging
import os
from typing import Dict, List, Optional, Set

import yaml

from pcluster.api.controllers.common import check_cluster_version, configure_aws_region
from pcluster.api.converters import cloud_formation_status_to_cluster_status
from pcluster.api.errors import (
    BadRequestException,
    ConflictException,
    CreateClusterBadRequestException,
    DryrunOperationException,
    InternalServiceException,
    NotFoundException,
)
from pcluster.api.models import (
    CloudFormationStatus,
    ClusterConfigurationStructure,
    ClusterInfoSummary,
    ConfigValidationMessage,
    CreateClusterBadRequestExceptionResponseContent,
    CreateClusterRequestContent,
    CreateClusterResponseContent,
    DeleteClusterResponseContent,
    DescribeClusterResponseContent,
    EC2Instance,
    InstanceState,
    ListClustersResponseContent,
    Tag,
    UpdateClusterRequestContent,
    UpdateClusterResponseContent,
    ValidationLevel,
)
from pcluster.api.models.cluster_status import ClusterStatus
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import StackNotFoundError
from pcluster.cli_commands.compute_fleet_status_manager import ComputeFleetStatus
from pcluster.config.common import AllValidatorsSuppressor, TypeMatchValidatorsSuppressor, ValidatorSuppressor
from pcluster.models.cluster import Cluster, ClusterActionError, ConfigValidationError
from pcluster.models.cluster_resources import ClusterStack
from pcluster.utils import get_installed_version
from pcluster.validators.common import FailureLevel, ValidationResult

LOGGER = logging.getLogger(__name__)


@configure_aws_region(is_query_string_arg=False)
def create_cluster(
    create_cluster_request_content: Dict,
    suppress_validators: List[str] = None,
    validation_failure_level: str = None,
    dryrun: bool = None,
    rollback_on_failure: bool = None,
    client_token: str = None,
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
    :param client_token: Idempotency token that can be set by the client so that retries for the same request are
    idempotent
    """
    # Set defaults
    rollback_on_failure = rollback_on_failure or True
    validation_failure_level = validation_failure_level or ValidationLevel.ERROR
    dryrun = dryrun or False
    create_cluster_request_content = CreateClusterRequestContent.from_dict(create_cluster_request_content)

    # Validate inputs
    if client_token:
        raise BadRequestException("clientToken is currently not supported for this operation")
    cluster_config_dict = _parse_cluster_config(create_cluster_request_content.cluster_configuration)

    # Check unique cluster name
    cluster = Cluster(create_cluster_request_content.name, cluster_config_dict)
    if AWSApi.instance().cfn.stack_exists(cluster.stack_name):
        raise ConflictException(f"cluster {cluster.name} already exists")

    # Create cluster
    try:
        stack_id, ignored_validation_failures = cluster.create(
            disable_rollback=not rollback_on_failure,
            validator_suppressors=_get_validator_suppressors(suppress_validators),
            validation_failure_level=FailureLevel[validation_failure_level],
            dryrun=dryrun,
        )

        if dryrun:
            LOGGER.info("Skipping cluster creation due to dryrun operation")
            raise DryrunOperationException()

        return CreateClusterResponseContent(
            ClusterInfoSummary(
                cluster_name=create_cluster_request_content.name,
                cloudformation_stack_status=CloudFormationStatus.CREATE_IN_PROGRESS,
                cloudformation_stack_arn=stack_id,
                region=os.environ.get("AWS_DEFAULT_REGION"),
                version=get_installed_version(),
                cluster_status=cloud_formation_status_to_cluster_status(CloudFormationStatus.CREATE_IN_PROGRESS),
            ),
            validation_messages=_build_validation_messages_list(ignored_validation_failures) or None,
        )
    except ConfigValidationError as e:
        raise _handle_config_validation_error(e)
    except ClusterActionError as e:
        # TODO: this currently might include also some failures that are due to a bad client request
        raise InternalServiceException(
            f"Failed when creating cluster due to: {e}. "
            "If you suppressed config validators this might be due to an invalid configuration file"
        )


@configure_aws_region()
def delete_cluster(cluster_name, region=None, retain_logs=None, client_token=None):
    """
    Initiate the deletion of a cluster.

    :param cluster_name: Name of the cluster
    :type cluster_name: str
    :param region: AWS Region. Defaults to the region the API is deployed to.
    :type region: str
    :param retain_logs: Retain cluster logs on delete. Defaults to True.
    :type retain_logs: bool
    :param client_token: Idempotency token that can be set by the client so that retries for the same request are
    idempotent
    :type client_token: str

    :rtype: DeleteClusterResponseContent
    """
    return DeleteClusterResponseContent(
        cluster=ClusterInfoSummary(
            cluster_name="nameeee",
            cloudformation_stack_status=CloudFormationStatus.CREATE_COMPLETE,
            cloudformation_stack_arn="arn",
            region="region",
            version="3.0.0",
            cluster_status=ClusterStatus.CREATE_COMPLETE,
        )
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
            f"cluster {cluster_name} does not exist or belongs to an incompatible ParallelCluster major version."
        )

    if not check_cluster_version(cluster):
        raise BadRequestException(f"cluster {cluster_name} belongs to an incompatible ParallelCluster major version.")

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
def update_cluster(
    update_cluster_request_content: Dict,
    cluster_name,
    suppress_validators=None,
    validation_failure_level=None,
    region=None,
    dryrun=None,
    force_update=None,
    client_token=None,
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
    :param client_token: Idempotency token that can be set by the client so that retries for the same request are
    idempotent
    :type client_token: str

    :rtype: UpdateClusterResponseContent
    """
    update_cluster_request_content = UpdateClusterRequestContent.from_dict(update_cluster_request_content)
    return UpdateClusterResponseContent(
        cluster=ClusterInfoSummary(
            cluster_name="nameeee",
            cloudformation_stack_status=CloudFormationStatus.CREATE_COMPLETE,
            cloudformation_stack_arn="arn",
            region="region",
            version="3.0.0",
            cluster_status=ClusterStatus.CREATE_COMPLETE,
        )
    )


def _build_validation_messages_list(config_validation_errors: List[ValidationResult]) -> List[ConfigValidationMessage]:
    configuration_validation_messages = []
    if config_validation_errors:
        for failure in config_validation_errors:
            configuration_validation_messages.append(
                ConfigValidationMessage(
                    level=ValidationLevel.from_dict(failure.level.name),
                    message=failure.message,
                    type=failure.validator_type,
                )
            )
    return configuration_validation_messages


def _handle_config_validation_error(e: ConfigValidationError) -> CreateClusterBadRequestException:
    config_validation_messages = _build_validation_messages_list(e.validation_failures)
    return CreateClusterBadRequestException(
        CreateClusterBadRequestExceptionResponseContent(
            configuration_validation_errors=config_validation_messages, message="Invalid cluster configuration"
        )
    )


def _parse_cluster_config(base64_encoded_config: str) -> Dict:
    try:
        cluster_config = base64.b64decode(base64_encoded_config).decode("UTF-8")
    except Exception as e:
        LOGGER.error("Failed when decoding cluster configuration: %s", e)
        raise BadRequestException("invalid cluster configuration. Please make sure the string is base64 encoded.")

    if not cluster_config:
        raise BadRequestException("cluster configuration is required and cannot be empty")

    try:
        config_dict = yaml.safe_load(cluster_config)
        if not isinstance(config_dict, dict):
            raise Exception("parsed config is not a dict")
        return config_dict
    except Exception as e:
        LOGGER.error("Failed when parsing the cluster configuration due to invalid YAML document: %s", e)
        raise BadRequestException("cluster configuration must be a valid base64-encoded YAML document")


def _get_validator_suppressors(suppress_validators: Optional[List[str]]) -> Set[ValidatorSuppressor]:
    validator_suppressors: Set[ValidatorSuppressor] = set()
    if not suppress_validators:
        return validator_suppressors

    validator_types_to_suppress = set()
    for suppress_validator_expression in suppress_validators:
        if suppress_validator_expression == "ALL":
            validator_suppressors.add(AllValidatorsSuppressor())
        elif suppress_validator_expression.startswith("type:"):
            validator_types_to_suppress.add(suppress_validator_expression[len("type:") :])  # noqa: E203

    if validator_types_to_suppress:
        validator_suppressors.add(TypeMatchValidatorsSuppressor(validator_types_to_suppress))

    return validator_suppressors
