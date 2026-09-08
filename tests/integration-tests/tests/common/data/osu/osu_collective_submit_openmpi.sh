#!/bin/bash
set -e

BENCHMARK_NAME={{ benchmark_name }}
OSU_BENCHMARK_VERSION={{ osu_benchmark_version }}
NUM_OF_PROCESSES={{ num_of_processes }}
REPETITIONS={{ repetitions }}
OSU_OPTIONS="{{ osu_options }}"

module load openmpi

env

# Run collective benchmark. The collective operations are close to what a real application looks like.
# -np total number of processes to run (all vCPUs * N compute nodes), divided by 2 if multithreading is disabled
for _ in $(seq ${REPETITIONS}); do
  mpirun -np ${NUM_OF_PROCESSES} /shared/openmpi/osu-micro-benchmarks-${OSU_BENCHMARK_VERSION}/mpi/collective/${BENCHMARK_NAME} ${OSU_OPTIONS}
done > /shared/${BENCHMARK_NAME}.out
