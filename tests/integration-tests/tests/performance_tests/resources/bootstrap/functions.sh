#!/bin/bash

function _log () {
  echo "$(date +"%Y-%m-%dT%H-%M-%S") [$1] $2"
}

function log () {
  _log "INFO" "$1"
}

function log_error () {
  _log "ERROR" "$1"
}

function fail () {
  log_error "$1"
  exit 1
}

function download_asset () {
  local s3_uri="$1"
  local local_file="$2"
  local permissions="$3"

  mkdir -p $(dirname "${local_file}")
  aws s3 cp "${s3_uri}" "${local_file}"
  chmod ${permissions} "${local_file}"
}

function cron_script () {
  local cron_expression="$1"
  local script="$2"
  local log="$3"

  echo "${cron_expression} ${script} > ${log} 2>&1" >> "/var/spool/cron/$(whoami)"
}

function timestamp_millis () {
  date +"%s%3N"
}

function timestamp_datetime () {
  date +"%Y-%m-%dT%H-%M-%S"
}

function millis_to_date_time () {
  date -d @${1::-3} +"%Y-%m-%dT%H-%M-%S"
}

function date_time_to_millis () {
  date -d ${1} +"%Y-%m-%dT%H-%M-%S"
}

function get_instance_id () {
  # This function uses IMDS to retrieve the instance id, so it can be used:
  # 1. in the head node only if the function is executed by a super user or if IMDS secured is disabled
  # 2. in a compute node, always as there is no IMDS lockdown in there
  local imds_endpoint="http://169.254.169.254/latest"
  local imds_token=$(curl -X PUT "${imds_endpoint}/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null)

  curl -H "aws-ec2-metadata-token: ${imds_token}" "${imds_endpoint}/meta-data/instance-id" 2>/dev/null
}

function wait_job_completion () {
  local job_ids=$1
  local sleep_seconds=$2
  local expected_jobs_in_queue=0

  while true; do
    local jobs_in_queue=$(/opt/slurm/bin/squeue -h -j${job_ids} | wc -l)
    log "Current jobs in queue: ${jobs_in_queue}. Expected jobs in queue: ${expected_jobs_in_queue}"
    [ ${jobs_in_queue} == ${expected_jobs_in_queue} ] && break
    log "Sleeping ${sleep_seconds} seconds"
    sleep ${sleep_seconds}
  done
}

function get_compute_fleet_running_nodes () {
  local cluster_name=$1
  local region=$2

  /usr/local/bin/pcluster describe-cluster-instances --region ${region} --cluster-name "${cluster_name}" --query 'instances[].nodeType'  | grep -o ComputeNode  | wc -l
}

function terminate_compute_fleet () {
    local cluster_name=$1
    local region=$2

    /usr/local/bin/pcluster delete-cluster-instances --region ${region} --cluster-name "${cluster_name}" --force true
}

function wait_compute_fleet () {
  local cluster_name=$1
  local region=$2
  local expected_compute_nodes=$3
  local sleep_seconds=$4

  while true; do
    local compute_nodes=$(get_compute_fleet_running_nodes ${cluster_name} ${region})
    log "Current compute nodes ${compute_nodes}. Expected compute nodes ${expected_compute_nodes}."
    [ ${compute_nodes} == ${expected_compute_nodes} ] && break
    log "Sleeping ${sleep_seconds} seconds"
    sleep ${sleep_seconds}
  done
}

function add_to_json () {
  local key=$1
  local value=$2
  local json_file=$3

  [[ ! -f ${json_file} ]] && echo "{}" > ${json_file}
  echo $(jq ".${key} = \"${value}\"" ${json_file}) > ${json_file}
}

function merge_json () {
  local json_file_1=$1
  local json_file_2=$2
  local json_file_3=$3

  echo $(jq --argfile f1 "${json_file_1}" --argfile f2 "${json_file_2}" -n '$f1 * $f2') > "${json_file_3}"
}

function get_sample_from_json () {
  local key="$1"
  local files="$2"

  jq -n "[inputs.${key}]" ${files} | jq -r -c 'map(select(length > 0)) | join(",")'
}

function get_json_with_minimum () {
  local key="$1"
  local files="$2"

  jq -n "[inputs] | sort_by(.${key}) | .[0]" ${files}
}

function get_json_with_maximum () {
  local key="$1"
  local files="$2"

  jq -n "[inputs] | sort_by(.${key}) | .[-1]" ${files}
}

function get_min () {
  python3 -c "print(min([${1}]))"
}

function get_max () {
  python3 -c "print(max([${1}]))"
}

function get_avg () {
  python3 -c "from statistics import mean;print(mean([${1}]))"
}

function get_std () {
  python3 -c "from statistics import stdev;print(stdev([${1}]))"
}

function get_med () {
  python3 -c "from statistics import median;print(median([${1}]))"
}

function get_prc () {
  python3 -c "from numpy import percentile;print(percentile([${1}], ${2}))"
}

function get_circular_array_element () {
  local position=${1}
  shift
  local array=("$@")
  local array_size=${#array[@]}
  local index=$(( ${position} % ${array_size} ))

  echo "${array[@]:${index}:1}"
}

function join_array_by {
  local d=${1-} a=${2-}

  if shift 2; then
    printf %s "$a" "${@/#/$d}"
  fi
}

function put_metric() {
  local region="$1"
  local namespace="$2"
  local dimensions="$3"
  local metric_name="$4"
  local value="$5"

  aws cloudwatch put-metric-data \
      --region "${region}" \
      --namespace "${namespace}" \
      --dimensions "${dimensions}" \
      --metric-name "${metric_name}" \
      --value "${value}"
}
