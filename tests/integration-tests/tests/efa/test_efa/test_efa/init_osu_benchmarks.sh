#!/usr/bin/env bash
set -e

module load ${1}
mkdir -p /shared/${1}
cd /shared/${1}
wget https://mvapich.cse.ohio-state.edu/download/mvapich/osu-micro-benchmarks-5.4.tar.gz
tar zxvf ./osu-micro-benchmarks-5.4.tar.gz
cd osu-micro-benchmarks-5.4/
./configure CC=$(which mpicc) CXX=$(which mpicxx)
make