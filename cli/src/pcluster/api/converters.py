#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
from typing import List

from pcluster.api.models import CloudFormationStackStatus, ClusterStatus, ConfigValidationMessage, ImageBuildStatus
from pcluster.api.models import NodeType as ApiNodeType
from pcluster.api.models import ValidationLevel
from pcluster.models.cluster import NodeType
from pcluster.validators.common import ValidationResult


def cloud_formation_status_to_cluster_status(cfn_status):
    mapping = {
        CloudFormationStackStatus.ROLLBACK_IN_PROGRESS: ClusterStatus.CREATE_FAILED,
        CloudFormationStackStatus.ROLLBACK_FAILED: ClusterStatus.CREATE_FAILED,
        CloudFormationStackStatus.ROLLBACK_COMPLETE: ClusterStatus.CREATE_FAILED,
        CloudFormationStackStatus.UPDATE_COMPLETE_CLEANUP_IN_PROGRESS: ClusterStatus.UPDATE_IN_PROGRESS,
        CloudFormationStackStatus.UPDATE_ROLLBACK_IN_PROGRESS: ClusterStatus.UPDATE_IN_PROGRESS,
        CloudFormationStackStatus.UPDATE_ROLLBACK_FAILED: ClusterStatus.UPDATE_FAILED,
        CloudFormationStackStatus.UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS: ClusterStatus.UPDATE_IN_PROGRESS,
        CloudFormationStackStatus.UPDATE_ROLLBACK_COMPLETE: ClusterStatus.UPDATE_FAILED,
    }
    return mapping.get(cfn_status, cfn_status)


def cloud_formation_status_to_image_status(cfn_status):
    mapping = {
        CloudFormationStackStatus.CREATE_IN_PROGRESS: ImageBuildStatus.BUILD_IN_PROGRESS,
        CloudFormationStackStatus.CREATE_FAILED: ImageBuildStatus.BUILD_FAILED,
        CloudFormationStackStatus.CREATE_COMPLETE: ImageBuildStatus.BUILD_COMPLETE,
        CloudFormationStackStatus.ROLLBACK_IN_PROGRESS: ImageBuildStatus.BUILD_FAILED,
        CloudFormationStackStatus.ROLLBACK_FAILED: ImageBuildStatus.BUILD_FAILED,
        CloudFormationStackStatus.ROLLBACK_COMPLETE: ImageBuildStatus.BUILD_FAILED,
        CloudFormationStackStatus.DELETE_IN_PROGRESS: ImageBuildStatus.DELETE_IN_PROGRESS,
        CloudFormationStackStatus.DELETE_FAILED: ImageBuildStatus.DELETE_FAILED,
        CloudFormationStackStatus.DELETE_COMPLETE: ImageBuildStatus.DELETE_COMPLETE,
        CloudFormationStackStatus.UPDATE_IN_PROGRESS: ImageBuildStatus.BUILD_IN_PROGRESS,
        CloudFormationStackStatus.UPDATE_COMPLETE_CLEANUP_IN_PROGRESS: ImageBuildStatus.BUILD_IN_PROGRESS,
        CloudFormationStackStatus.UPDATE_COMPLETE: ImageBuildStatus.BUILD_COMPLETE,
        CloudFormationStackStatus.UPDATE_ROLLBACK_IN_PROGRESS: ImageBuildStatus.BUILD_IN_PROGRESS,
        CloudFormationStackStatus.UPDATE_ROLLBACK_FAILED: ImageBuildStatus.BUILD_FAILED,
        CloudFormationStackStatus.UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS: ImageBuildStatus.BUILD_IN_PROGRESS,
        CloudFormationStackStatus.UPDATE_ROLLBACK_COMPLETE: ImageBuildStatus.BUILD_FAILED,
    }
    return mapping.get(cfn_status, cfn_status)


def validation_results_to_config_validation_errors(
    config_validation_errors: List[ValidationResult],
) -> List[ConfigValidationMessage]:
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


def api_node_type_to_cluster_node_type(node_type: ApiNodeType):
    mapping = {
        ApiNodeType.HEADNODE: NodeType.HEAD_NODE,
        ApiNodeType.COMPUTENODE: NodeType.COMPUTE,
        ApiNodeType.LOGINNODE: NodeType.LOGIN_NODE,
    }
    return mapping.get(node_type)
