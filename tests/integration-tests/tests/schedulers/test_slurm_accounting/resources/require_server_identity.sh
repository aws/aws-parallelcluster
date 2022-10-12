#!/bin/bash

set -e

CA_URL=$1
CA_NAME=$2
CA_PATH="/tmp/slurm"
CA_FILE_PATH="${CA_PATH}/${CA_NAME}"
SLURMDBD_CONFIG_FILE="/opt/slurm/etc/slurmdbd.conf"

wget ${CA_URL} -nH -x --cut-dirs=1 -P ${CA_PATH}

echo "Clearing previous CA Setting"
sed -i "s/^StorageParameters=.*$//g" "${SLURMDBD_CONFIG_FILE}"
echo "StorageParameters=" >> "${SLURMDBD_CONFIG_FILE}"

echo "Setting 'StorageParameters' SSL_CA=${CA_FILE_PATH}"
sed -i "s:^StorageParameters=.*$:StorageParameters=SSL_CA=${CA_FILE_PATH}:g" "${SLURMDBD_CONFIG_FILE}"

echo "Restarting slurmdbd service"
systemctl restart slurmdbd
