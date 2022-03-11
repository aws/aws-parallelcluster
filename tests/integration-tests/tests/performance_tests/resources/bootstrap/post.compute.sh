#!/bin/bash
set -ex

# Cluster variables
source /etc/parallelcluster/cfnconfig
SHARED_DIR="$(echo $cfn_ebs_shared_dirs | cut -d ',' -f 1)"

# Load libraries
FUNCTIONS_SCRIPT="${SHARED_DIR}/assets/lib/functions.sh"
source "${FUNCTIONS_SCRIPT}"

# Instance Details
INSTANCE_ID=$(get_instance_id)

# Monitoring
INSTANCE_METRICS_DIR="${SHARED_DIR}/metrics/compute-nodes"
INSTANCE_METRICS_FILE="${INSTANCE_METRICS_DIR}/instance-${INSTANCE_ID}.json"
INSTANCE_METRICS_PRE_FILE="/local/parallelcluster/monitoring/instance-metrics.json"
mkdir -m 777 -p ${INSTANCE_METRICS_DIR}

# Monitoring - PreInstall Metrics
cp ${INSTANCE_METRICS_PRE_FILE} ${INSTANCE_METRICS_FILE}

# Monitoring - Start Time (milliseconds)
INSTANCE_START_TIME=$(date +"%s%3N")
add_to_json "instancePostInstallTimestamp" ${INSTANCE_START_TIME} ${INSTANCE_METRICS_FILE}

# Monitoring - Up Time (seconds)
INSTANCE_UPTIME=$(cat /proc/uptime | cut -d ' ' -f 1 | cut -d '.' -f 1)
add_to_json "instancePostInstallUpTime" ${INSTANCE_UPTIME} ${INSTANCE_METRICS_FILE}

# Monitoring - InstanceId
add_to_json "instanceId" ${INSTANCE_ID} ${INSTANCE_METRICS_FILE}

chmod 666 ${INSTANCE_METRICS_FILE}
