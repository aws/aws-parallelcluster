#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
from pcluster.api.models import CloudFormationStatus, ClusterStatus


def cloud_formation_status_to_cluster_status(cfn_status):
    mapping = {
        CloudFormationStatus.ROLLBACK_IN_PROGRESS: ClusterStatus.CREATE_FAILED,
        CloudFormationStatus.ROLLBACK_FAILED: ClusterStatus.CREATE_FAILED,
        CloudFormationStatus.ROLLBACK_COMPLETE: ClusterStatus.CREATE_FAILED,
        CloudFormationStatus.UPDATE_COMPLETE_CLEANUP_IN_PROGRESS: ClusterStatus.UPDATE_IN_PROGRESS,
        CloudFormationStatus.UPDATE_ROLLBACK_IN_PROGRESS: ClusterStatus.UPDATE_IN_PROGRESS,
        CloudFormationStatus.UPDATE_ROLLBACK_FAILED: ClusterStatus.UPDATE_FAILED,
        CloudFormationStatus.UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS: ClusterStatus.UPDATE_IN_PROGRESS,
        CloudFormationStatus.UPDATE_ROLLBACK_COMPLETE: ClusterStatus.UPDATE_FAILED,
    }
    return mapping.get(cfn_status, cfn_status)
