#!/usr/bin/env bash

# This prolog script configures the NVIDIA IMEX nodes config file and reloads the nvidia-imex service.
# This prolog is meant to be run by compute nodes.

LOG_FILE_PATH="/var/log/parallelcluster/nvidia-imex-prolog.log"
DNA_JSON_FILE="/etc/chef/dna.json"
SCONTROL_CMD="/opt/slurm/bin/scontrol"
IMEX_START_TIMEOUT=60
IMEX_STOP_TIMEOUT=15
WAIT_TIME_TO_STABILIZE=30
#TODO In production, specify p6e-gb200, only. We added g5g only for testing purposes.
ALLOWED_INSTANCE_TYPES="^(p6e-gb200|g5g)"
IMEX_SERVICE="nvidia-imex"

# Global service lock to prevent concurrent service operations
SERVICE_LOCK_FILE="/var/lock/nvidia-imex-service.lock"
SERVICE_LOCK_TIMEOUT=120

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

function return_unless_gb200_with_imex() {
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

function get_dna_parameter() {
  jq -r ".cluster.${1}" "${DNA_JSON_FILE}"
}

function write_file() {
  local _file=$1
  local _content=$2
  local _lock_file="${_file}.lock"
  local _lock_timeout_seconds=60
  local _max_retries=3
  local _retry_count=0

  if [[ -f "${_file}" ]] && [[ "$(cat "${_file}")" = "${_content}" ]]; then
    info "File ${_file} already has the expected content, skipping the write operation"
    return 1 # Not Updated
  fi

  while [[ ${_retry_count} -lt ${_max_retries} ]]; do
    (
        if flock -x -w ${_lock_timeout_seconds} 200; then
          echo "${_content}" > "${_file}"
          exit 0
        else
          exit 1
        fi
    ) 200>"${_lock_file}"
    
    local _lock_result=$?
    
    if [[ ${_lock_result} -eq 0 ]]; then
      return 0 # Updated successfully
    fi
    
    _retry_count=$((_retry_count + 1))
    info "Lock acquisition failed for ${_file}, retry ${_retry_count}/${_max_retries}"
    
    # Only remove stale lock if it's older than timeout + buffer
    if [[ -f "${_lock_file}" ]]; then
      local _lock_age=$(($(date +%s) - $(stat -c %Y "${_lock_file}" 2>/dev/null || echo 0)))
      if [[ ${_lock_age} -gt $((${_lock_timeout_seconds} + 30)) ]]; then
        info "Removing stale lock file ${_lock_file} (age: ${_lock_age}s)"
        rm -f "${_lock_file}"
      fi
    fi
    
    sleep $((${_retry_count} * 2))  # Exponential backoff
  done
  
  error_exit "Failed to acquire lock for ${_file} after ${_max_retries} retries"
}

function reload_imex() {
  info "Attempting to acquire service lock for IMEX reload"
  
  # Use a global lock to prevent concurrent service operations
  (
    if ! flock -x -w ${SERVICE_LOCK_TIMEOUT} 201; then
      error "Failed to acquire service lock within ${SERVICE_LOCK_TIMEOUT}s"
      exit 1
    fi
    
    info "Service lock acquired, proceeding with IMEX reload"
    
    info "Stopping IMEX"
    timeout ${IMEX_STOP_TIMEOUT} systemctl stop ${IMEX_SERVICE}
    pkill -9 ${IMEX_SERVICE}

    #TODO Improvement: rotate server port to prevent race condition
    # info "Rotating server port in IMEX config ${IMEX_MAIN_CONFIG}"
    # NEW_SERVER_PORT=$((${SLURM_JOB_ID} % 16384 + 33792))
    # sed -i "s/SERVER_PORT.*/SERVER_PORT=${NEW_SERVER_PORT}/" "${IMEX_MAIN_CONFIG}"

    info "Restarting IMEX"
    timeout ${IMEX_START_TIMEOUT} systemctl start ${IMEX_SERVICE}
    
  ) 201>"${SERVICE_LOCK_FILE}"
  
  local _service_result=$?
  if [[ ${_service_result} -ne 0 ]]; then
    error "IMEX service reload failed"
    return 1
  fi
  
  return 0
}

# Use process-specific log file to avoid concurrent write issues
PROCESS_LOG_FILE="${LOG_FILE_PATH}.${SLURM_JOB_ID}.$$"

{
  info "PROLOG Start JobId=${SLURM_JOB_ID}: $0"

  return_unless_gb200_with_imex

  QUEUE_NAME=$(get_dna_parameter "scheduler_queue_name")
  COMPUTE_RESOURCE_NAME=$(get_dna_parameter "scheduler_compute_resource_name")
  LAUNCH_TEMPLATE_ID=$(get_dna_parameter "launch_template_id")
  CR_NODES=$(get_node_names "${QUEUE_NAME}" "${COMPUTE_RESOURCE_NAME}")
  IPS_FROM_CR=$(get_ips_from_node_names "${CR_NODES}")
  IMEX_MAIN_CONFIG="/opt/parallelcluster/shared/nvidia-imex/config_${LAUNCH_TEMPLATE_ID}.cfg"
  IMEX_NODES_CONFIG="/opt/parallelcluster/shared/nvidia-imex/nodes_config_${LAUNCH_TEMPLATE_ID}.cfg"

  info "Queue Name: ${QUEUE_NAME}"
  info "CR Name: ${COMPUTE_RESOURCE_NAME}"
  info "CR Nodes: ${CR_NODES}"
  info "Launch Template Id: ${LAUNCH_TEMPLATE_ID}"
  info "Node IPs from CR: ${IPS_FROM_CR}"
  info "IMEX Main Config: ${IMEX_MAIN_CONFIG}"
  info "IMEX Nodes Config: ${IMEX_NODES_CONFIG}"

  info "Updating IMEX nodes config ${IMEX_NODES_CONFIG}"
  if write_file "${IMEX_NODES_CONFIG}" "${IPS_FROM_CR}"; then
    info "IMEX nodes config updated, reloading service"
    if reload_imex; then
      info "Sleeping ${WAIT_TIME_TO_STABILIZE} seconds to let IMEX stabilize"
      sleep ${WAIT_TIME_TO_STABILIZE}
    else
      error "Failed to reload IMEX service"
    fi
  else
    info "IMEX nodes config unchanged, skipping service reload"
  fi

  prolog_end

} >> "${PROCESS_LOG_FILE}" 2>&1

# Append to main log file with lock protection
(
  flock -x -w 10 202 && cat "${PROCESS_LOG_FILE}" >> "${LOG_FILE_PATH}"
  rm -f "${PROCESS_LOG_FILE}"
) 202>"${LOG_FILE_PATH}.append.lock" 2>/dev/null
