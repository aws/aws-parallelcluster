#!/bin/bash
#
# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

# Usage: mount_filesystem.sh efs_fs_id aws_region shared_dir

error_exit_usage() {
    echo "Error executing script: $1"
    usage
    exit 1
}

error_exit() {
    echo "Error executing script: $1"
    exit 1
}

usage() {
    cat <<ENDUSAGE
    This script mounts EFS filesystem on shared dir on the nodes in the batch job.
    The shared directory will be created if it does not exist.

    USAGE:
    mount_nfs <efs_fs_id> <aws_region> <shared_dir>
    efs_fs_id: if of EFS file system
    aws_region: AWS region of the stack
    shared_dir: directory for EFS file system to be mounted on. If directory doesn't exist on compute, will be created
ENDUSAGE
}

# Check that the arguments are valid
check_arguments_valid(){
    if [ -z "${efs_fs_id}" ]; then
        error_exit_usage "EFS FS Id is a required argument"
    fi

    if [ -z "${aws_region}" ]; then
        error_exit_usage "AWS region is a required argument"
    fi

    if [ -z "${shared_dir}" ]; then
        error_exit_usage "The directory to be shared via nfs is a required argument"
    fi
}

# mount nfs
mount_nfs() {

    error_message=$(rpcinfo &> /dev/null || rpcbind 2>&1)
    if [[ $? -ne 0 ]]; then
        error_exit "Failed to run rpcbind with error_message: ${error_message}"
    fi

    mkdir -p ${shared_dir}
    error_message=$(mount -t nfs4 -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport,_netdev "${efs_dir}" "${shared_dir}" 2>&1)
    if [[ $? -ne 0 ]]; then
        error_exit "Failed to mount nfs volume from ${efs_dir} with error_message: ${error_message}"
    fi

    # Check that the filesystem is mounted as appropriate
    mount_line=$(mount | grep "${efs_dir}")
    if [[ -z "${mount_line}" ]]; then
        error_exit "mount succeeded but nfs volume from ${efs_dir} was not mounted as expected"
    fi
}


# main function
main() {
    efs_fs_id=${1}
    aws_region=${2}
    aws_domain="amazonaws.com"
    if [[ ${aws_region} == cn-* ]]; then
        aws_domain="amazonaws.com.cn"
    elif [[ ${aws_region} == us-iso-* ]]; then
        aws_domain="c2s.ic.gov"
    elif [[ ${aws_region} == us-isob-* ]]; then
        aws_domain="sc2s.sgov.gov"
    fi
    efs_dir="${efs_fs_id}.efs.${aws_region}.${aws_domain}:/"
    shared_dir="/${3}"

    check_arguments_valid
    mount_nfs
}

main "$@"
