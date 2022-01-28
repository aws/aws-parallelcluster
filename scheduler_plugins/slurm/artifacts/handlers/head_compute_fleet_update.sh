#!/bin/bash

#
# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
#

set -e

sudo "${PCLUSTER_PYTHON_ROOT}/supervisorctl" -c "${PCLUSTER_LOCAL_SCHEDULER_PLUGIN_DIR}/supervisord.conf" stop clustermgtd
sudo "${PCLUSTER_LOCAL_SCHEDULER_PLUGIN_DIR}/scripts/slurm/slurm_fleet_status_manager" -cf "${PCLUSTER_COMPUTEFLEET_STATUS}"
sudo "${PCLUSTER_PYTHON_ROOT}/supervisorctl" -c "${PCLUSTER_LOCAL_SCHEDULER_PLUGIN_DIR}/supervisord.conf" start clustermgtd
