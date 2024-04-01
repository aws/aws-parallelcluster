#!/bin/bash
# Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

CLUSTERMGTD_LOG="/var/log/parallelcluster/clustermgtd"
touch "bootstrap_errors.txt"

# Find a log message like:
# ... WARNING - Node bootstrap error: Node queue-0-dy-compute-resource-0-1690(192.168.90.197) ...
# and get the IP address
sudo cat ${CLUSTERMGTD_LOG} | grep -i "Node bootstrap error" | awk -F"[()]" '{print $2}' | while read -r ip_address ; do
  if ! grep -q "${ip_address}" "bootstrap_errors.txt"; then
    echo "${ip_address}" >> "bootstrap_errors.txt"
  fi
done
