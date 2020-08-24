#!/usr/bin/env bash
set -e

OSU_BENCHMARKS_VERSION=5.6.3

module load ${1}
mkdir -p /shared/${1}
cp "./osu-micro-benchmarks-${OSU_BENCHMARKS_VERSION}.tar.gz" /shared/${1}
cd /shared/${1}
tar zxvf "./osu-micro-benchmarks-${OSU_BENCHMARKS_VERSION}.tar.gz"
cd "osu-micro-benchmarks-${OSU_BENCHMARKS_VERSION}/"
./configure CC=$(which mpicc) CXX=$(which mpicxx)
make
