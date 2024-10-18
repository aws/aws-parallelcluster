#!/bin/bash
set -ex

# Installs Fabtests suite from GitHub.
# Usage: install-fabtests.sh [FABTESTS_DIR]
# Example: install-fabtests.sh /shared/fabtests

FABTESTS_DIR="$1"

FABTESTS_REPO="https://github.com/ofiwg/libfabric.git"
FABTESTS_VERSION="1.22.0"
FABTESTS_SOURCES_DIR="$FABTESTS_DIR/sources"
LIBFABRIC_DIR="/opt/amazon/efa"
CUDA_DIR="/usr/local/cuda"

echo "[INFO] Installing Fabtests in $FABTESTS_DIR"
rm -rf $FABTESTS_DIR
mkdir -p $FABTESTS_SOURCES_DIR
cd $FABTESTS_SOURCES_DIR
git clone --depth 1 --branch v$FABTESTS_VERSION $FABTESTS_REPO
cd libfabric/fabtests
./autogen.sh
./configure --with-libfabric=$LIBFABRIC_DIR --with-cuda=$CUDA_DIR --prefix=$FABTESTS_DIR && make -j 32 && make install
python3 -m pip install --user -r $FABTESTS_SOURCES_DIR/libfabric/fabtests/pytest/requirements.txt
echo "[INFO] Fabtests installed in $FABTESTS_DIR"
