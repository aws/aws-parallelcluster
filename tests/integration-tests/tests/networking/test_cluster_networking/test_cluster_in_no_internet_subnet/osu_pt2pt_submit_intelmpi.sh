#!/bin/bash
#SBATCH --ntasks=2 --nodes=2

set -e

module load intelmpi
srun --mpi=pmi2 /shared/intelmpi/osu-micro-benchmarks-{{ osu_benchmark_version }}/mpi/pt2pt/osu_latency
mpirun --map-by ppr:1:node /shared/intelmpi/osu-micro-benchmarks-{{ osu_benchmark_version }}/mpi/pt2pt/osu_latency