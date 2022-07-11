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

# Usage: mount_filesystem.sh head_node_ip shared_dir

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
This script mounts the shared dir from head node instance on the nodes in the batch job.
The shared directory will be created if it does not exist.

USAGE:
mount_nfs <head_node_ip> <shared_dir>
head_node_ip: ip address of the main node
shared_dir: directory from head node to be shared. If directory doesn't exist on compute, will be created
ENDUSAGE
}

# Check that the arguments are valid
check_arguments_valid(){
    if [ -z "${head_node_ip}" ]; then
        error_exit_usage "Head Node IP is a required argument"
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
    error_message=$(mount -t nfs -o hard,intr,noatime,_netdev "${head_node_ip}":"${shared_dir}" "${shared_dir}" 2>&1)
    if [[ $? -ne 0 ]]; then
        error_exit "Failed to mount nfs volume from ${head_node_ip}:${shared_dir} with error_message: ${error_message}"
    fi

    # Check that the filesystem is mounted as appropriate
    mount_line=$(mount | grep "${head_node_ip}:${shared_dir}")
    if [[ -z "${mount_line}" ]]; then
        error_exit "mount succeeded but nfs volume from ${head_node_ip}:${shared_dir} was not mounted as expected"
    fi
}


# main function
main() {
    head_node_ip=${1}
    shared_dir=${2}
    if [[ "${shared_dir:0:1}" != '/' ]]; then
      shared_dir="/${shared_dir}"
    fi

    check_arguments_valid
    mount_nfs
}

main "$@"
