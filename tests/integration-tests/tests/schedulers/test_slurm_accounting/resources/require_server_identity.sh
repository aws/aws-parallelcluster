#!/bin/bash

set -e

CA_URL=$1
CA_NAME=$2
CA_PATH="/tmp/slurm"
CA_FILE_PATH="${CA_PATH}/${CA_NAME}"
SLURMDBD_CONFIG_FILE="/opt/slurm/etc/slurmdbd.conf"

wget ${CA_URL} -P ${CA_PATH}

echo "Clearing previous CA Setting"
sed -i "/^StorageParameters\s*=/d" "${SLURMDBD_CONFIG_FILE}"

echo "Setting 'StorageParameters' SSL_CA=${CA_FILE_PATH}"
echo "StorageParameters=SSL_CA=${CA_FILE_PATH}" >> "${SLURMDBD_CONFIG_FILE}"

echo "Restarting slurmdbd service"
systemctl restart slurmdbd
