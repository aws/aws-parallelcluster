#!/bin/bash
#
# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy
# of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, express or implied. See the License for the specific
# language governing permissions and limitations under the License.

# Usage:
#   modify_china_yum_vars.sh <region>

usage() {
    cat <<ENDUSAGE
This script modifies yum repo variables so that the Amazon Linux 2 repo points to China-specific URLs.
The modification is only made if the cluster is running in a China region.

USAGE:
modify_china_yum_vars.sh <region>
region: Region which cluster is running in
ENDUSAGE

}

error_exit_usage() {
    echo "Error executing script: $1"
    usage
    exit 1
}

main() {

    if [ $# -ne 1 ]; then
        error_exit_usage "Wrong number of arguments provided"
    fi

    # Only modify yum repo variables if cluster is running in a China region.
    REGION="${1}"
    if [[ "${REGION}" =~ ^cn-.* ]]; then
        echo "amazonlinux-2-repos-${REGION}.s3" > /etc/yum/vars/amazonlinux
        echo "amazonaws.com.cn" > /etc/yum/vars/awsdomain
        echo "https" > /etc/yum/vars/awsproto
        echo "${REGION}" > /etc/yum/vars/awsregion
    else
        echo "Not running in China region. Skipping modification of yum variables."
    fi
}

main "$@"
