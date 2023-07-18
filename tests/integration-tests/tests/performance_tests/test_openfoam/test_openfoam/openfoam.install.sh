#!/bin/bash
#the script installs OpenFOAM in a shared folder that is shared with all the cluster nodes
set -ex

TARGET_USER=$(whoami)

SHARED_DIR="/shared"
TARGET_USER_DIR="${SHARED_DIR}/${TARGET_USER}"

SUBSPACE_BENCHMARKS_PACKAGE_ZIP="${TARGET_USER_DIR}/SubspaceBenchmarks.tar"

mkdir -p "${TARGET_USER_DIR}"
cd "${TARGET_USER_DIR}"

aws s3 cp s3://performance-tests-resources-for-parallelcluster/openfoam/SubspaceBenchmarks.tar ${SUBSPACE_BENCHMARKS_PACKAGE_ZIP}
tar -xf SubspaceBenchmarks.tar
chmod -R 777 $(basename ${SUBSPACE_BENCHMARKS_PACKAGE_ZIP})
