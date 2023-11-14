#!/bin/bash
#the script installs StarCCM+ in a shared folder that is shared with all the cluster nodes
set -ex

TARGET_USER=$(whoami)

SHARED_DIR="/shared" # /shared or whatever you named the SharedStorage MountDir
TARGET_USER_DIR="${SHARED_DIR}/${TARGET_USER}"

STARCCM_PACKAGE="${TARGET_USER_DIR}/STAR-CCM+18.02.008_01_linux-x86_64.tar.gz"
SIM_FILE="${TARGET_USER_DIR}/lemans_poly_17m.amg@00500.sim"

mkdir -p "${TARGET_USER_DIR}"

OLD_PWD=$(pwd)

cd "${TARGET_USER_DIR}"

aws s3 cp s3://performance-tests-resources-for-parallelcluster/starccm/STAR-CCM+18.02.008_01_linux-x86_64.tar.gz ${STARCCM_PACKAGE}
tar -xf $(basename ${STARCCM_PACKAGE})

aws s3 cp s3://performance-tests-resources-for-parallelcluster/starccm/lemans_poly_17m.amg@00500.sim ${SIM_FILE}

cd starccm+_18.02.008
# (executed by the below printf) During the installation, you need to type: <ENTER>, Y, N, /shared/${TARGET_USER}/STAR-CCM+, Y, <ENTER>, <ENTER>
printf "\nY\nN\n${TARGET_USER_DIR}/STAR-CCM+\nY\n\n\n" | ./STAR-CCM+18.02.008_01_linux-x86_64-2.17_gnu11.2.sh

rm -rf ${STARCCM_PACKAGE}

cd ${OLD_PWD}
