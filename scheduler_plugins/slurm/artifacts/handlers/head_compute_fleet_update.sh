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

# FIXME: temporary workaround
PLUGIN_TABLE=$(jq -r .Outputs.DynamoDBTable ${PCLUSTER_SCHEDULER_PLUGIN_CFN_SUBSTACK_OUTPUTS})
STATUS=$(jq -r .status ${PCLUSTER_COMPUTEFLEET_STATUS})
LAST_UPDATED_TIME=$(jq -r .lastStatusUpdatedTime ${PCLUSTER_COMPUTEFLEET_STATUS})
aws dynamodb put-item --table-name "${PLUGIN_TABLE}"\
    --item "{\"Id\": {\"S\": \"COMPUTE_FLEET\"}, \"Status\": {\"S\": \"${STATUS}\"}, \"LastUpdatedTime\": {\"S\": \"${LAST_UPDATED_TIME}\"}}"\
    --region ${PCLUSTER_AWS_REGION}
sleep 120
