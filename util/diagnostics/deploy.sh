#!/bin/bash
# Uploads the diagnostics folder to the head node of a ParallelCluster and installs dependencies.
#
# Usage:
#   bash deploy.sh --cluster-name <cluster-name> --region <region> [--ssh-key <path-to-key>]
#
# Example:
#   bash deploy.sh --cluster-name my-cluster --region us-east-1 --ssh-key ~/.ssh/my-key.pem
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    echo "Usage: $0 --cluster-name <cluster-name> --region <region> [--ssh-key <path>]"
    echo ""
    echo "Upload the diagnostics folder to the head node of a ParallelCluster."
    echo ""
    echo "Options:"
    echo "  --cluster-name, -n   Name of the cluster"
    echo "  --region, -r         AWS region"
    echo "  --ssh-key, -i        Path to the SSH private key"
    exit "${1:-1}"
}

CLUSTER_NAME=""
REGION=""
SSH_KEY=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cluster-name|-n) CLUSTER_NAME="$2"; shift 2 ;;
        --region|-r) REGION="$2"; shift 2 ;;
        --ssh-key|-i) SSH_KEY="$2"; shift 2 ;;
        --help|-h) usage 0 ;;
        *) echo "[ERROR] Unknown option: $1"; usage ;;
    esac
done

if [[ -z "$CLUSTER_NAME" || -z "$REGION" ]]; then
    usage
fi

if [[ -n "$SSH_KEY" && ! -f "$SSH_KEY" ]]; then
    echo "[ERROR] SSH key file not found: $SSH_KEY"
    exit 1
fi

echo "[INFO] Retrieving head node connection info for cluster '${CLUSTER_NAME}' in region '${REGION}'..."

# Check pcluster is available
if ! command -v pcluster &>/dev/null; then
    echo "[ERROR] 'pcluster' command not found. Please install the AWS ParallelCluster CLI."
    exit 1
fi

# Run pcluster ssh dryrun; on failure, surface the CLI error directly
PCLUSTER_OUTPUT=$(pcluster ssh -n "$CLUSTER_NAME" -r "$REGION" --dryrun true 2>&1) || {
    echo "[ERROR] pcluster command failed: ${PCLUSTER_OUTPUT}"
    exit 1
}

SSH_CMD=$(echo "$PCLUSTER_OUTPUT" | python3 -c "import sys, json; print(json.load(sys.stdin)['command'])" 2>/dev/null)

if [[ -z "$SSH_CMD" ]]; then
    echo "[ERROR] Could not parse pcluster ssh output: '${PCLUSTER_OUTPUT}'"
    exit 1
fi

# Extract user and IP from "ssh <user>@<ip>"
USER_AT_IP=$(echo "$SSH_CMD" | awk '{print $2}')
DEFAULT_USER="${USER_AT_IP%%@*}"
HEAD_NODE_IP="${USER_AT_IP##*@}"

if [[ -z "$DEFAULT_USER" || -z "$HEAD_NODE_IP" ]]; then
    echo "[ERROR] Could not parse user and IP from pcluster ssh output: '${SSH_CMD}'"
    exit 1
fi

echo "[INFO] Head node IP: ${HEAD_NODE_IP}"
echo "[INFO] Default user: ${DEFAULT_USER}"
echo "[INFO] Uploading ${SCRIPT_DIR} to ${DEFAULT_USER}@${HEAD_NODE_IP}:~/"

REMOTE_DIR="$(basename "$SCRIPT_DIR")"

# Build rsync and ssh args as arrays to safely handle paths with spaces
RSYNC_ARGS=(-av --exclude="README.md" --exclude="deploy.sh" --exclude="__pycache__")
SSH_ARGS=()
if [[ -n "$SSH_KEY" ]]; then
    RSYNC_ARGS+=(-e "ssh -i ${SSH_KEY}")
    SSH_ARGS+=(-i "${SSH_KEY}")
fi

rsync "${RSYNC_ARGS[@]}" "$SCRIPT_DIR" "${DEFAULT_USER}@${HEAD_NODE_IP}:~/"

echo "[INFO] Done. Files uploaded to /home/${DEFAULT_USER}/${REMOTE_DIR}/"

echo "[INFO] Installing requirements on head node..."

ssh "${SSH_ARGS[@]}" "${DEFAULT_USER}@${HEAD_NODE_IP}" "pip install -r ~/${REMOTE_DIR}/requirements.txt"

echo "[INFO] Requirements installed successfully."
echo "[INFO] Next steps: log into the head node and run the diagnostics scripts from ~/${REMOTE_DIR}/"
SSH_LOGIN_CMD="ssh"
[[ -n "$SSH_KEY" ]] && SSH_LOGIN_CMD+=" -i ${SSH_KEY}"
SSH_LOGIN_CMD+=" ${DEFAULT_USER}@${HEAD_NODE_IP} -t 'cd ~/${REMOTE_DIR} && bash -l'"
echo "[INFO]   ${SSH_LOGIN_CMD}"
