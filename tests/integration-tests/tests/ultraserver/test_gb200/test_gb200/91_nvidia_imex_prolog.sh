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

function check_imex_needs_reload() {
  local _expected_ips=$1
  local _imex_config_file=$2
  
  # First check if IMEX service is running
  if ! systemctl is-active ${IMEX_SERVICE} &>/dev/null; then
    info "IMEX service is not running, reload needed"
    return 0  # Need reload
  fi
  
  # Get current IMEX status
  local imex_status_output
  if ! imex_status_output=$(timeout 15 /usr/bin/nvidia-imex-ctl -N -j -c "${_imex_config_file}" 2>/dev/null); then
    info "Failed to get IMEX status, assuming reload needed"
    return 0  # Need reload
  fi
  
  # Parse JSON to extract current IPs from IMEX status
  local current_imex_ips
  if ! current_imex_ips=$(echo "${imex_status_output}" | jq -r '.nodes | to_entries[].value.host' 2>/dev/null | sort | tr '\n' ' '); then
    info "Failed to parse IMEX status JSON, assuming reload needed"
    return 0  # Need reload
  fi
  
  # Convert expected IPs to sorted space-separated string
  local expected_ips_sorted
  expected_ips_sorted=$(echo "${_expected_ips}" | tr ',' '\n' | sort | tr '\n' ' ')
  
  info "Current IMEX IPs: ${current_imex_ips}"
  info "Expected IPs: ${expected_ips_sorted}"
  
  # Compare IP lists
  if [[ "${current_imex_ips}" = "${expected_ips_sorted}" ]]; then
    info "IMEX service running with correct IPs, skipping reload"
    return 1  # Skip reload
  else
    info "IMEX IPs mismatch, reload needed"
    return 0  # Need reload
  fi
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
  if ! timeout ${IMEX_START_TIMEOUT} systemctl start ${IMEX_SERVICE}; then
    error "IMEX service reload failed"
    return 1
  fi
  
  return 0
}

function handle_imex_reload() {
  local _ips_from_cr=$1
  local _imex_main_config=$2
  local _reload_reason=$3
  local _skip_message=$4
  local _reload_message=$5
  
  info "${_reload_reason}"
  if check_imex_needs_reload "${_ips_from_cr}" "${_imex_main_config}"; then
    info "${_reload_message}"
    if reload_imex; then
      info "Sleeping ${WAIT_TIME_TO_STABILIZE} seconds to let IMEX stabilize"
      sleep ${WAIT_TIME_TO_STABILIZE}
    else
      error "Failed to reload IMEX service"
    fi
  else
    info "${_skip_message}"
  fi
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

  return_unless_gb200_with_imex

  create_default_imex_channel

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

  info "Checking IMEX nodes config ${IMEX_NODES_CONFIG}"
  if write_file "${IMEX_NODES_CONFIG}" "${IPS_FROM_CR}"; then
    handle_imex_reload "${IPS_FROM_CR}" "${IMEX_MAIN_CONFIG}" "IMEX nodes config updated, checking if reload is needed" "IMEX already configured correctly, skipping reload" "IMEX reload needed, restarting service"
  else
    handle_imex_reload "${IPS_FROM_CR}" "${IMEX_MAIN_CONFIG}" "IMEX nodes config unchanged, checking if reload is still needed" "IMEX config unchanged and service correctly configured, skipping reload" "IMEX reload needed despite unchanged config, restarting service"
  fi

  prolog_end

} >> "${LOG_FILE_PATH}" 2>&1
