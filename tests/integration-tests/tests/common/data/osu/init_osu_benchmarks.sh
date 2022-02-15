#!/usr/bin/env bash
set -e

MPI_VERSION=${1}

OSU_BENCHMARKS_VERSION={{ osu_benchmark_version }}
OSU_BENCHMARKS_PACKAGE_NAME="osu-micro-benchmarks-${OSU_BENCHMARKS_VERSION}"
OSU_BENCHMARKS_INSTALLATION_DIR="/shared/${MPI_VERSION}/${OSU_BENCHMARKS_PACKAGE_NAME}/"

# If the compilation directory already exists, skip the compilation.
[ -d "${OSU_BENCHMARKS_INSTALLATION_DIR}" ] && exit 0

module load ${MPI_VERSION}
mkdir -p /shared/${MPI_VERSION}

#wget --no-check-certificate http://mvapich.cse.ohio-state.edu/download/mvapich/${OSU_BENCHMARKS_PACKAGE_NAME}.tgz
cp "./${OSU_BENCHMARKS_PACKAGE_NAME}.tgz" /shared/${MPI_VERSION}
cd /shared/${MPI_VERSION}
tar zxvf "./${OSU_BENCHMARKS_PACKAGE_NAME}.tgz"

# Update config.guess and config.sub files to support ARM architecture.
cd
cp "./config.guess" "${OSU_BENCHMARKS_INSTALLATION_DIR}"
cp "./config.sub" "${OSU_BENCHMARKS_INSTALLATION_DIR}"

# Compile OSU benchmarks
cd "${OSU_BENCHMARKS_INSTALLATION_DIR}"
./configure CC=$(which mpicc) CXX=$(which mpicxx)
make
