#!/bin/bash
set -ex

# Executes Fabtests suite.
# Usage: run-fabtests.sh [FABTESTS_DIR] [PID_FILE] [LOG_FILE] [REPORT_FILE] [COMPUTE_NODE_1] [COMPUTE_NODE_2] [TEST_CASES] [TEST_OPTIONS]
# Example:
# run-fabtests.sh \
# /shared/fabtests \
# /shared/fabtests/outputs/fabtests.pid \
# /shared/fabtests/outputs/fabtests.log \
# /shared/fabtests/outputs/fabtests.report \
# q1-st-g4dn8xl-efa-1 q1-st-g4dn8xl-efa-2 \
# rdm_tagged_bw,rdm_tagged_pingpong \
# enable-gdr

FABTESTS_DIR="$1"
PID_FILE="$2"
LOG_FILE="$3"
REPORT_FILE="$4"
COMPUTE_NODE_1="$5"
COMPUTE_NODE_2="$6"
TEST_CASES="$7"
TEST_OPTIONS="$8"

echo "[INFO] Starting Fabtests ($FABTESTS_DIR) using compute nodes $COMPUTE_NODE_1 and $COMPUTE_NODE_2: $TEST_CASES"
echo "[INFO] Fabtests will use the following test environment options: $TEST_OPTIONS"
echo "[INFO] Fabtests pid will be stored in $PID_FILE"
echo "[INFO] Fabtests logs will be stored in $LOG_FILE"
echo "[INFO] Fabtests report will be stored in $REPORT_FILE"

FABTESTS_BIN_DIR="$FABTESTS_DIR/bin"
FABTESTS_RUNNER="$FABTESTS_BIN_DIR/runfabtests.py"
FABTESTS_TIMEOUT="300" # Timeout for each test
COMPUTE_IP_1=$(host $COMPUTE_NODE_1 | cut -d ' ' -f 4)
COMPUTE_IP_2=$(host $COMPUTE_NODE_2 | cut -d ' ' -f 4)
TEST_EXPRESSION=${TEST_CASES//,/ or }
TEST_ENVIRONMENT_OPTION=""
[[ "$TEST_OPTIONS" == *"enable-gdr"* ]] && TEST_ENVIRONMENT_OPTION="-E FI_EFA_USE_DEVICE_RDMA=1"

mkdir -p $(dirname $PID_FILE)
mkdir -p $(dirname $LOG_FILE)
mkdir -p $(dirname $REPORT_FILE)

python3 $FABTESTS_RUNNER \
  -b efa \
  -p "$FABTESTS_BIN_DIR" \
  --expression "$TEST_EXPRESSION" \
  --timeout $FABTESTS_TIMEOUT \
  --junit-xml $REPORT_FILE \
  $TEST_ENVIRONMENT_OPTION $COMPUTE_IP_1 $COMPUTE_IP_2 > $LOG_FILE 2>&1 &

echo $! > $PID_FILE

echo "[INFO] Fabtests launched"