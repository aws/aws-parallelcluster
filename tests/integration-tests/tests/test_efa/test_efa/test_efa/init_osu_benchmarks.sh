#!/usr/bin/env bash
set -e

cd /shared
wget http://mvapich.cse.ohio-state.edu/download/mvapich/osu-micro-benchmarks-5.4.tar.gz
tar zxvf ./osu-micro-benchmarks-5.4.tar.gz
cd osu-micro-benchmarks-5.4/
./configure CC=/opt/amazon/efa/bin/mpicc CXX=/opt/amazon/efa/bin/mpicxx
make