#!/bin/bash
#SBATCH --ntasks=2 --nodes=2

set -e

module load openmpi
mpirun --map-by ppr:1:node /shared/openmpi/osu-micro-benchmarks-{{ osu_benchmark_version }}/mpi/pt2pt/osu_latency
