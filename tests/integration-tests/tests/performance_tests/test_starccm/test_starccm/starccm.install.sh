#!/bin/bash
#the script installs StarCCM+ in a shared folder that is shared with all the cluster nodes
set -ex

TARGET_USER=$(whoami)

SHARED_DIR="/shared" # /shared or whatever you named the SharedStorage MountDir
TARGET_USER_DIR="${SHARED_DIR}/${TARGET_USER}"

STARCCM_PACKAGE_ZIP="${TARGET_USER_DIR}/pc211debug.tgz"

mkdir -p "${TARGET_USER_DIR}"

OLD_PWD=$(pwd)

cd "${TARGET_USER_DIR}"

aws s3 cp s3://kkolurbucket/pc211debug.tgz ${STARCCM_PACKAGE_ZIP}
tar -xf $(basename ${STARCCM_PACKAGE_ZIP})

STARCCM_INSTALLER_ZIP="STAR-CCM+16.02.008_01_linux-x86_64-2.17_gnu9.2.zip"
unzip ${STARCCM_INSTALLER_ZIP}
cd STAR-CCM+16.02.008_01_linux-x86_64-2.17_gnu9.2
# (exeucted by the below printf) During the installation, you need to type: <ENTER>, Y, N, /shared/${TARGET_USER}/STAR-CCM+, Y, <ENTER>, <ENTER>
printf "\nY\nN\n${TARGET_USER_DIR}/STAR-CCM+\nY\n\n\n" | ./STAR-CCM+16.02.008_01_linux-x86_64-2.17_gnu9.2.sh

rm -rf ${STARCCM_PACKAGE_ZIP}
rm -rf ${STARCCM_INSTALLER_ZIP}

cd ${OLD_PWD}
