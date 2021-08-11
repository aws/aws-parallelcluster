#!/bin/bash
set -e

BENCHMARK_NAME={{ benchmark_name }}
OSU_BENCHMARK_VERSION={{ osu_benchmark_version }}
NUM_OF_PROCESSES={{ num_of_processes }}

module load intelmpi
# Run collective benchmark. The collective operations are close to what a real application looks like.
# NOTE: The test is sized for 4 compute nodes.
# -np total number of processes to run (all CPUs * 4 nodes)
mpirun -np ${NUM_OF_PROCESSES} -rr /shared/intelmpi/osu-micro-benchmarks-${OSU_BENCHMARK_VERSION}/mpi/collective/${BENCHMARK_NAME} > /shared/${BENCHMARK_NAME}.out
