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

# Usage:
#   generate_hostfile.sh <shared_dir> <destination_dir>

usage() {
    cat <<ENDUSAGE
This script generates a hostfile which contains the ip addresses of the compute nodes

USAGE:
generate_hostfile <shared_dir> <destination_dir>
shared_dir: Shared directory on which compute and head instances have agreed upon for reading and writing the ip addresses. Directory needs to exist. A temporary directory is created inside this directory
destination_dir: Directory where hostfile should reside. Directory needs to exist
ENDUSAGE

}

error_exit_usage() {
    echo "Error executing script: $1"
    usage
    exit 1
}

error_exit() {
    echo "Error executing script: $1"
    exit 1
}

# Check that the arguments are valid
check_arguments_valid() {
    if [ -z "${shared_dir}" ]; then
        error_exit_usage "Shared directory is a required argument"
    fi

    if [ -z "${destination_dir}" ]; then
        error_exit_usage "Destination directory is a required argument"
    fi

    if [ ! -d "${shared_dir}" ]; then
        error_exit "Shared directory ${shared_dir} does not exist"
    fi

    if [ ! -d "${destination_dir}" ]; then
        error_exit "Destination directory ${destination_dir} does not exist"
    fi
}

# Check that the necessary batch variables exist, else exit
check_batch_env_variables_exist() {
    if [[ -z "${AWS_BATCH_JOB_NODE_INDEX}" ]]; then
        error_exit "AWS_BATCH_JOB_NODE_INDEX is expected to exist but does not exist."
    fi

    if [[ -z "${AWS_BATCH_JOB_MAIN_NODE_INDEX}" ]]; then
        error_exit "AWS_BATCH_JOB_MAIN_NODE_INDEX is expected to exist but does not exist."
    fi

    if [[ -z "${AWS_BATCH_JOB_NUM_NODES}" ]]; then
        error_exit "AWS_BATCH_JOB_NUM_NODES is expected to exist but does not exist."
    fi

    if [[ -z "${AWS_BATCH_JOB_ID}" ]]; then
        error_exit "AWS_BATCH_JOB_ID is expected to exist but does not exist."
    fi

    if [[ -z "${AWS_BATCH_JOB_ATTEMPT}" ]]; then
        error_exit "AWS_BATCH_JOB_ATTEMPT is expected to exist but does not exist."
    fi
}

# On the head node populate the hostfile with the ip addresses and available cores of the compute nodes
read_compute_address() {
    if [[ ! -f "${destination_dir}/hostfile" ]]; then
        touch "${destination_dir}/hostfile"
    fi

    compute_nodes_read=0

    while [[ "${AWS_BATCH_JOB_NUM_NODES}" -gt ${compute_nodes_read} ]]; do
        for fullfile in "${shared_dir_temp}"/* ; do
            file=$(basename "${fullfile}")
            if [[ ${file} = "*" ]]; then
                # No files found in ${shared_dir_temp} yet
                break
            fi

            if ! [[ ${file} =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
                error_exit "Matched filename not in expected format on head node: ${file}"
            fi

            cat "${fullfile}" >> "${destination_dir}/hostfile"
            rm -rf "${fullfile}"
            (( compute_nodes_read += 1 ))
        done
        echo "Detected ${compute_nodes_read}/${AWS_BATCH_JOB_NUM_NODES} compute nodes. Waiting for all compute nodes to start."
        sleep 15
    done

    if [[ "$(ls -A "${shared_dir_temp}")" ]]; then
        error_exit "head node failed to read some of the ip addresses while generating the hostfile. Shared temp directory is not empty"
    elif [[ $(wc -l < "${destination_dir}/hostfile") -ne ${AWS_BATCH_JOB_NUM_NODES} ]]; then
        error_exit "The number of entries in hostfile is not equal to the AWS_BATCH_JOB_NUM_NODES"
    else
        rmdir "${shared_dir_temp}"
    fi
}

# Write a file in the shared dir with container ip address and available cores.
write_node_info() {
  ip_address=$(/sbin/ip -o -4 addr list eth0 | awk '{print $4}' | cut -d/ -f1)
  if ! [[ ${ip_address} =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
    error_exit "Matched IP Address not in expected format on compute node: ${ip_address}"
  fi
  available_cores=$(nproc --all)
  echo "${ip_address} slots=${available_cores}" > "${shared_dir_temp}/${ip_address}"
}


main() {

    if [ $# -ne 2 ]; then
        error_exit_usage "Wrong number of arguments provided"
    fi

    # This is the shared directory on which compute and head instances have agreed upon for reading and writing the ip addresses
    shared_dir="${1}"
    if [[ "${shared_dir:0:1}" != '/' ]]; then
      shared_dir="/${shared_dir}"
    fi
    destination_dir=${2}

    check_arguments_valid
    check_batch_env_variables_exist

    # AWS_BATCH_JOB_ID is in the format job_id#node_id. Stripping #node_id.
    shared_dir_temp="${shared_dir}/${AWS_BATCH_JOB_ID%#*}-${AWS_BATCH_JOB_ATTEMPT}"

    mkdir -p "${shared_dir_temp}"

    write_node_info
    # If it is the head inspect the shared directory for the hostfile list
    if [[ "${AWS_BATCH_JOB_NODE_INDEX}" -eq  "${AWS_BATCH_JOB_MAIN_NODE_INDEX}" ]]; then
        read_compute_address
    fi
}

main "$@"
