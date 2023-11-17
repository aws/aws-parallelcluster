#!/bin/bash
#the script installs OpenFOAM in a shared folder that is shared with all the cluster nodes
set -ex

SHARED_DIR="/shared"

SUBSPACE_BENCHMARKS_PACKAGE_ZIP="${SHARED_DIR}/SubspaceBenchmarks.tar"

cd "${SHARED_DIR}"

aws s3 cp s3://performance-tests-resources-for-parallelcluster/openfoam/SubspaceBenchmarks.tar ${SUBSPACE_BENCHMARKS_PACKAGE_ZIP}
tar -xf SubspaceBenchmarks.tar
chmod -R 777 $(basename ${SUBSPACE_BENCHMARKS_PACKAGE_ZIP})
