#!/usr/bin/env bash

# This prolog script configures the NVIDIA IMEX on compute nodes involved in the job execution.
#
# In particular:
# - Checks whether the job is executed exclusively.
#   If not, it exits immediately because it requires jobs to be executed exclusively.
# - Checks if it is running on a p6e-gb200 instance type.
#   If not, it exits immediately because IMEX must be configured only on that instance type.
# - Checks if the IMEX service is enabled.
#   If not, it exits immediately because IMEX must be enabled to get configured.
# - Creates the IMEX default channel.
#   For more information about IMEX channels, see https://docs.nvidia.com/multi-node-nvlink-systems/imex-guide/imexchannels.html
# - Writes the private IP addresses of compute nodes into /etc/nvidia-imex/nodes_config.cfg.
# - Restarts the IMEX system service.
#
# REQUIREMENTS:
#  - This prolog assumes to be run only with exclusive jobs.

LOG_FILE_PATH="/var/log/parallelcluster/nvidia-imex-prolog.log"
SCONTROL_CMD="/opt/slurm/bin/scontrol"
IMEX_START_TIMEOUT=60
IMEX_STOP_TIMEOUT=15
#TODO In production, specify p6e-gb200, only. We added g5g only for testing purposes.
ALLOWED_INSTANCE_TYPES="^(p6e-gb200|g5g)"
IMEX_SERVICE="nvidia-imex"
IMEX_NODES_CONFIG="/etc/nvidia-imex/nodes_config.cfg"

function info() {
  echo "$(date "+%Y-%m-%dT%H:%M:%S.%3N") [INFO] [PID:$$] [JOB:${SLURM_JOB_ID}] $1"
}

function warn() {
  echo "$(date "+%Y-%m-%dT%H:%M:%S.%3N") [WARN] [PID:$$] [JOB:${SLURM_JOB_ID}] $1"
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
}

function return_if_imex_disabled() {
  if ! systemctl is-enabled "${IMEX_SERVICE}" &>/dev/null; then
    warn "Skipping IMEX configuration because system service ${IMEX_SERVICE} is not enabled"
    prolog_end
  fi
}

function return_if_job_is_not_exclusive() {
  if [[ "${SLURM_JOB_OVERSUBSCRIBE}" =~ ^(NO|TOPO)$  ]]; then
    info "Job is exclusive, proceeding with IMEX configuration"
  else
    info "Skipping IMEX configuration because the job is not exclusive"
    prolog_end
  fi
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
  info "Creating IMEX default channel"
  MAJOR_NUMBER=$(cat /proc/devices | grep nvidia-caps-imex-channels | cut -d' ' -f1)
  if [ ! -d "/dev/nvidia-caps-imex-channels" ]; then
    sudo mkdir /dev/nvidia-caps-imex-channels
  fi

  # Then check and create device node
  if [ ! -e "/dev/nvidia-caps-imex-channels/channel0" ]; then
    sudo mknod /dev/nvidia-caps-imex-channels/channel0 c $MAJOR_NUMBER 0
    info "IMEX default channel created"
  else
    info "IMEX default channel already exists"
  fi
}

{
  info "PROLOG Start JobId=${SLURM_JOB_ID}: $0"

  return_if_job_is_not_exclusive
  return_if_unsupported_instance_type
  return_if_imex_disabled

  create_default_imex_channel

  IPS_FROM_CR=$(get_ips_from_node_names "${SLURM_NODELIST}")

  info "Node Names: ${SLURM_NODELIST}"
  info "Node IPs: ${IPS_FROM_CR}"
  info "IMEX Nodes Config: ${IMEX_NODES_CONFIG}"

  info "Updating IMEX nodes config ${IMEX_NODES_CONFIG}"
  echo "${IPS_FROM_CR}" > "${IMEX_NODES_CONFIG}"
  reload_imex

  prolog_end

} 2>&1 | tee -a "${LOG_FILE_PATH}" | logger -t "91_nvidia_imex_prolog"
