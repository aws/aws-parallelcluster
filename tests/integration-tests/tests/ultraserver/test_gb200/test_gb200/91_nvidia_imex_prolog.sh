#!/usr/bin/env bash

# This prolog script configures the NVIDIA IMEX nodes config file and reloads the nvidia-imex service.
# This prolog is meant to be run by compute nodes with exclusive jobs.

LOG_FILE_PATH="/var/log/parallelcluster/nvidia-imex-prolog.log"
SCONTROL_CMD="/opt/slurm/bin/scontrol"
IMEX_START_TIMEOUT=60
IMEX_STOP_TIMEOUT=15
#TODO In production, specify p6e-gb200, only. We added g5g only for testing purposes.
ALLOWED_INSTANCE_TYPES="^(p6e-gb200|g5g)"
IMEX_SERVICE="nvidia-imex"

function info() {
  echo "$(date "+%Y-%m-%dT%H:%M:%S.%3N") [INFO] [PID:$$] [JOB:${SLURM_JOB_ID}] $1"
}

function error() {
  echo "$(date "+%Y-%m-%dT%H:%M:%S.%3N") [ERROR] [PID:$$] [JOB:${SLURM_JOB_ID}] $1"
}

function error_exit() {
  error "$1" && exit 1
}

function prolog_end() {
    info "PROLOG End JobId=${SLURM_JOB_ID}: $0"
    info "----------------"
    exit 0
}

function get_instance_type() {
  local token=$(curl -X PUT -s "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
  curl -s -H "X-aws-ec2-metadata-token: ${token}" http://169.254.169.254/latest/meta-data/instance-type
}

function return_if_unsupported_instance_type() {
  local instance_type=$(get_instance_type)

  if [[ ! ${instance_type} =~ ${ALLOWED_INSTANCE_TYPES} ]]; then
    info "Skipping IMEX configuration because instance type ${instance_type} does not support it"
    prolog_end
  fi

  if ! systemctl is-enabled ${IMEX_SERVICE} &>/dev/null; then
    info "Skipping IMEX configuration because system service ${IMEX_SERVICE} is not enabled"
    prolog_end
  fi
}

function get_node_names() {
  local _queue_name=$1
  local _compute_resource_name=$2

  ${SCONTROL_CMD} show nodes --json | \
    jq -r \
      --arg queue_name "${_queue_name}" \
      --arg compute_resource_name "${_compute_resource_name}" \
      '[
        .nodes[] |
        select(
          (.partitions[] | contains($queue_name)) and
          (.features[] | contains($compute_resource_name)) and
          (.features[] | contains("static"))
        ) |
        .name
      ] |
      join(",")'
}

function get_ips_from_node_names() {
  local _nodes=$1
  #TODO Exclude non IP values, e.g. hostnames (q1-st-cr1-2) for compute nodes that are initializing
  ${SCONTROL_CMD} -ao show node "${_nodes}" | sed 's/^.* NodeAddr=\([^ ]*\).*/\1/'
}

function get_compute_resource_name() {
  local _queue_name_prefix=$1
  local _slurmd_node_name=$2
  echo "${_slurmd_node_name}" | sed -E "s/${_queue_name_prefix}(.+)-[0-9]+$/\1/"
}

function write_file() {
  local _file=$1
  local _content=$2
  local _lock_file="${_file}.lock"
  local _lock_timeout_seconds=60

  if [[ -f "${_file}" ]] && [[ "$(cat "${_file}")" = "${_content}" ]]; then
    info "File ${_file} already has the expected content, skipping the write operation"
    return 1 # Not Updated
  fi

  # Try to acquire lock with timeout
  (
      if ! flock -x -w ${_lock_timeout_seconds} 200; then
        # If timeout, assume deadlock and try to recover
        info "Lock timeout after ${_lock_timeout_seconds}s, attempting deadlock recovery"
        exit 1
      fi
      echo "${_content}" > "${_file}"
  ) 200>"${_lock_file}"

  local _lock_result=$?

  if [[ ${_lock_result} -eq 0 ]]; then
    return 0 # Updated successfully
  fi

  # Deadlock recovery: remove stale lock file and retry once
  error "Potential deadlock detected for ${_file}, attempting recovery"
  rm -f "${_lock_file}"
  sleep 1  # Brief pause to avoid race conditions

  (
      if ! flock -x -w 10 200; then
        exit 1
      fi
      echo "${_content}" > "${_file}"
  ) 200>"${_lock_file}"

  if [[ $? -eq 0 ]]; then
    info "Lock acquired after deadlock recovery for ${_file}"
    return 0 # Updated
  fi
  
  error_exit "Failed to acquire lock for ${_file} even after deadlock recovery"
}

function reload_imex() {
  info "Stopping IMEX"
  timeout ${IMEX_STOP_TIMEOUT} systemctl stop ${IMEX_SERVICE}
  pkill -9 ${IMEX_SERVICE}

  #TODO Improvement: rotate server port to prevent race condition
  # info "Rotating server port in IMEX config ${IMEX_MAIN_CONFIG}"
  # NEW_SERVER_PORT=$((${SLURM_JOB_ID} % 16384 + 33792))
  # sed -i "s/SERVER_PORT.*/SERVER_PORT=${NEW_SERVER_PORT}/" "${IMEX_MAIN_CONFIG}"

  info "Restarting IMEX"
  timeout ${IMEX_START_TIMEOUT} systemctl start ${IMEX_SERVICE}
}

function create_default_imex_channel() {
  # This configuration follows
  # [Nvidia doc](https://docs.nvidia.com/multi-node-nvlink-systems/imex-guide/imexchannels.html)
  # This configuration is only suitable for single user environment, and not compatible with multi-user environment.
  info "Creating IMEX default Channel"
  MAJOR_NUMBER=$(cat /proc/devices | grep nvidia-caps-imex-channels | cut -d' ' -f1)
  if [ ! -d "/dev/nvidia-caps-imex-channels" ]; then
    sudo mkdir /dev/nvidia-caps-imex-channels
  fi

  # Then check and create device node
  if [ ! -e "/dev/nvidia-caps-imex-channels/channel0" ]; then
    sudo mknod /dev/nvidia-caps-imex-channels/channel0 c $MAJOR_NUMBER 0
    info "IMEX default Channel created"
  else
    info "IMEX default Channel already exists"
  fi
}

{
  info "PROLOG Start JobId=${SLURM_JOB_ID}: $0"

  return_if_unsupported_instance_type

  create_default_imex_channel

  QUEUE_NAME=$SLURM_JOB_PARTITION
  COMPUTE_RESOURCE_NAME=$(get_compute_resource_name "${QUEUE_NAME}-st-" $SLURMD_NODENAME)
  CR_NODES=$(get_node_names "${QUEUE_NAME}" "${COMPUTE_RESOURCE_NAME}")
  IPS_FROM_CR=$(get_ips_from_node_names "${CR_NODES}")
  IMEX_MAIN_CONFIG="/opt/parallelcluster/shared/nvidia-imex/config_${QUEUE_NAME}_${COMPUTE_RESOURCE_NAME}.cfg"
  IMEX_NODES_CONFIG="/opt/parallelcluster/shared/nvidia-imex/nodes_config_${QUEUE_NAME}_${COMPUTE_RESOURCE_NAME}.cfg"

  info "Queue Name: ${QUEUE_NAME}"
  info "CR Name: ${COMPUTE_RESOURCE_NAME}"
  info "CR Nodes: ${CR_NODES}"
  info "Node IPs from CR: ${IPS_FROM_CR}"
  info "IMEX Main Config: ${IMEX_MAIN_CONFIG}"
  info "IMEX Nodes Config: ${IMEX_NODES_CONFIG}"

  info "Updating IMEX nodes config ${IMEX_NODES_CONFIG}"
  write_file "${IMEX_NODES_CONFIG}" "${IPS_FROM_CR}"

  reload_imex

  prolog_end

} >> "${LOG_FILE_PATH}" 2>&1
