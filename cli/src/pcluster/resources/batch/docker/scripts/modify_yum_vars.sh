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
This script modifies yum repo variables so that the Amazon Linux 2 repo points to the region-specific URLs for China and Isolated regions.
The modification is only made if the cluster is running in a China or Isolated region.

USAGE:
modify_yum_vars.sh <region>
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

    # Modify yum repo variables if cluster is running in a region with non default AWS domain.
    local REGION="${1}"
    local AWS_DOMAIN="amazonaws.com"
    if [[ ${REGION} == cn-* ]]; then
        AWS_DOMAIN="amazonaws.com.cn"
    elif [[ ${REGION} == us-iso-* ]]; then
        AWS_DOMAIN="c2s.ic.gov"
    elif [[ ${REGION} == us-isob-* ]]; then
        AWS_DOMAIN="sc2s.sgov.gov"
    fi
    if [[ ${AWS_DOMAIN} != "amazonaws.com" ]]; then
        echo "amazonlinux-2-repos-${REGION}.s3" > /etc/yum/vars/amazonlinux
        echo "${AWS_DOMAIN}" > /etc/yum/vars/awsdomain
        echo "https" > /etc/yum/vars/awsproto
        echo "${REGION}" > /etc/yum/vars/awsregion
    else
        echo "Not running in China or Isolated region. Skipping modification of yum variables."
    fi
}

main "$@"
