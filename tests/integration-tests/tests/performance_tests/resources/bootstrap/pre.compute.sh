#!/bin/bash
set -ex

# Monitoring
INSTANCE_METRICS_FILE="/local/parallelcluster/monitoring/instance-metrics.json"
mkdir -p $(dirname "${INSTANCE_METRICS_FILE}")
echo "{}" > ${INSTANCE_METRICS_FILE}

# Monitoring - Start Time (milliseconds)
INSTANCE_START_TIME=$(date +"%s%3N")
echo $(jq ".instancePreInstallTimestamp = \"${INSTANCE_START_TIME}\"" ${INSTANCE_METRICS_FILE}) > ${INSTANCE_METRICS_FILE}

# Monitoring - Up Time (seconds)
INSTANCE_UPTIME=$(cat /proc/uptime | cut -d ' ' -f 1 | cut -d '.' -f 1)
echo $(jq ".instancePreInstallUpTime = \"${INSTANCE_UPTIME}\"" ${INSTANCE_METRICS_FILE}) > ${INSTANCE_METRICS_FILE}
