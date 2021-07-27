#!/bin/bash

set -ex

nvswitches=$(lspci -d 10de:1af1 | wc -l)

#if [ "${nvswitches}" -gt "1" ]; then
#    # From https://docs.nvidia.com/datacenter/tesla/tesla-installation-notes/index.html#ubuntu-lts
#    distribution=$(. /etc/os-release;echo ${ID}${VERSION_ID} | sed -e 's/\.//g')
#    echo "deb http://developer.download.nvidia.com/compute/cuda/repos/${distribution}/x86_64 /" | sudo tee /etc/apt/sources.list.d/cuda.list
#    sudo apt update -y
#
#    driver_version=$(nvidia-smi | grep -oP "(?<=Driver Version: )[0-9.]+")
#    driver_major=$(echo ${driver_version} | cut -d. -f1)
#
#    sudo apt-get install -y --allow-downgrades nvidia-fabricmanager-${driver_major}=${driver_version}*
#    sudo apt-mark hold nvidia-fabricmanager-${driver_major}
#    sudo systemctl enable nvidia-fabricmanager.service
#    sudo systemctl start nvidia-fabricmanager.service
#fi
#
