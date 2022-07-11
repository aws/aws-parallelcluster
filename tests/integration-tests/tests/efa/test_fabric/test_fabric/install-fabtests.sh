#!/bin/bash
set -ex

# Installs Fabtests suite from GitHub.
# Usage: install-fabtests.sh [FABTESTS_DIR]
# Example: install-fabtests.sh /home/ec2-user/shared/fabtests

FABTESTS_DIR="$1"

FABTESTS_REPO="https://github.com/ofiwg/libfabric.git"  # TODO Replace with released tarball v1.16.0 once available
FABTESTS_SOURCES_DIR="$FABTESTS_DIR/sources"
LIBFABRIC_DIR="/opt/amazon/efa"

echo "[INFO] Installing Fabtests in $FABTESTS_DIR"
rm -rf $FABTESTS_DIR
mkdir -p $FABTESTS_SOURCES_DIR
cd $FABTESTS_SOURCES_DIR
git clone $FABTESTS_REPO
cd libfabric/fabtests
./autogen.sh
./configure --with-libfabric=$LIBFABRIC_DIR --prefix=$FABTESTS_DIR && make -j 32 && make install
python3 -m pip install -r $FABTESTS_SOURCES_DIR/libfabric/fabtests/pytest/requirements.txt
python3 -m pip install pyyaml # TODO This is required but it is missing in the above requirements.txt
echo "[INFO] Fabtests installed in $FABTESTS_DIR"