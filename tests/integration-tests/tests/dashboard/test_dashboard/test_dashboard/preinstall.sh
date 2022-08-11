#!/bin/bash
# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
function get_instance_type() {
  token=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
  instance_type_url="http://169.254.169.254/latest/meta-data/instance-type"
  instance_type=$(curl --retry 3 --retry-delay 0 --silent --fail -H "X-aws-ec2-metadata-token: ${token}" "${instance_type_url}")
}
get_instance_type
if [ "${instance_type}" == "c5.large" ]; then
  echo "Test Bootstrap error that causes instance to self terminate."
  exit 1
fi
