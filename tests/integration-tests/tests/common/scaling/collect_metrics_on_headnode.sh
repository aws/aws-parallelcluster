#!/bin/bash
# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.

set -ex

NODE_COUNT=$(sudo -i sinfo --Node --noheader --responding -o '%t' | grep -v '[*#~%]' | wc -l)
PENDING_JOBS_COUNT=$(squeue -h -t configuring,pending | wc -l)
RUNNING_JOBS_COUNT=$(squeue -h -t running | wc -l)

cat << EOF > "scaling_metrics.json"
{"NodeCount": "$NODE_COUNT", "PendingJobsCount": "$PENDING_JOBS_COUNT", "RunningJobsCount": "$RUNNING_JOBS_COUNT"}
EOF
