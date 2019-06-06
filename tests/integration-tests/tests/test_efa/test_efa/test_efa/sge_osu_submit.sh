#!/bin/bash
#$ -pe mpi 144

cd /shared/osu-micro-benchmarks-5.4
sudo make install  # on all compute nodes

# actually run the benchmark
module load openmpi
mpirun -N 1 -np 2 /usr/local/libexec/osu-micro-benchmarks/mpi/pt2pt/osu_latency