#!/bin/bash
set -ex

# Installs Fabtests suite from GitHub.
# Usage: install-fabtests.sh [FABTESTS_DIR]
# Example: install-fabtests.sh /shared/fabtests

FABTESTS_DIR="$1"

FABTESTS_REPO="https://github.com/ofiwg/libfabric.git"
FABTESTS_VERSION="1.21.0"
FABTESTS_SOURCES_DIR="$FABTESTS_DIR/sources"
LIBFABRIC_DIR="/opt/amazon/efa"
CUDA_DIR="/usr/local/cuda"

echo "[INFO] Checking OS info"
. /etc/os-release
OS="${NAME}-${VERSION_ID}"
echo "[INFO] OS is ${OS}"

echo "[INFO] Installing Fabtests in $FABTESTS_DIR"
rm -rf $FABTESTS_DIR
mkdir -p $FABTESTS_SOURCES_DIR
cd $FABTESTS_SOURCES_DIR
git clone --depth 1 --branch v$FABTESTS_VERSION $FABTESTS_REPO
cd libfabric/fabtests
./autogen.sh

./configure --with-libfabric=$LIBFABRIC_DIR --with-cuda=$CUDA_DIR --prefix=$FABTESTS_DIR && make -j 32 && make install

# On Ubuntu 24.04 we must disable the externally managed flag to unblock installation of custom python packages
# on the system installation of Python.
# This is only a workaround to quickly unblock the test.
# the long term solution is to define a virtualenv to run Fabtests.
# See https://packaging.python.org/en/latest/specifications/externally-managed-environments/
if [[ ${OS} == "Ubuntu-24.04" ]]; then
  PYTHON_STDLIB_DIR=$(python3 -c 'import sysconfig;print(sysconfig.get_path("stdlib", sysconfig.get_default_scheme()))')
  echo "[INFO] Removing EXTERNALLY-MANAGED flag for system installation of Python at ${PYTHON_STDLIB_DIR}, as a workaround to unblock Fabtests installation on OS ${OS}"
  sudo rm -rf "${PYTHON_STDLIB_DIR}/EXTERNALLY-MANAGED"
fi
python3 -m pip install --user -r $FABTESTS_SOURCES_DIR/libfabric/fabtests/pytest/requirements.txt
echo "[INFO] Fabtests installed in $FABTESTS_DIR"
