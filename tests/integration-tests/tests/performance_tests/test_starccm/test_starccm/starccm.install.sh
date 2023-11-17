#!/bin/bash
#the script installs StarCCM+ in a shared folder that is shared with all the cluster nodes
set -ex

SHARED_DIR="/shared" # /shared or whatever you named the SharedStorage MountDir

STARCCM_PACKAGE_ZIP="${SHARED_DIR}/pc211debug.tgz"

OLD_PWD=$(pwd)

cd "${SHARED_DIR}"

aws s3 cp s3://performance-tests-resources-for-parallelcluster/starccm/pc211debug.tgz ${STARCCM_PACKAGE_ZIP}
tar -xf $(basename ${STARCCM_PACKAGE_ZIP})

STARCCM_INSTALLER_ZIP="STAR-CCM+16.02.008_01_linux-x86_64-2.17_gnu9.2.zip"
unzip ${STARCCM_INSTALLER_ZIP}
cd STAR-CCM+16.02.008_01_linux-x86_64-2.17_gnu9.2
# (executed by the below printf) During the installation, you need to type: <ENTER>, Y, N, /shared/STAR-CCM+, Y, <ENTER>, <ENTER>
printf "\nY\nN\n${SHARED_DIR}/STAR-CCM+\nY\n\n\n" | ./STAR-CCM+16.02.008_01_linux-x86_64-2.17_gnu9.2.sh

rm -rf ${STARCCM_PACKAGE_ZIP}
rm -rf ${STARCCM_INSTALLER_ZIP}

cd ${OLD_PWD}
