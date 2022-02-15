#!/bin/bash
set -e

BENCHMARK_NAME={{ benchmark_name }}
OSU_BENCHMARK_VERSION={{ osu_benchmark_version }}

module load intelmpi
export I_MPI_DEBUG=10
env

mpirun -np 2 -bootstrap=slurm --map-by ppr:1:node /shared/intelmpi/osu-micro-benchmarks-${OSU_BENCHMARK_VERSION}/mpi/pt2pt/${BENCHMARK_NAME} > /shared/${BENCHMARK_NAME}.out
