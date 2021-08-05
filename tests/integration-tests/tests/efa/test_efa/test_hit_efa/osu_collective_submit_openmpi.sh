#!/bin/bash
set -e

BENCHMARK_NAME={{ benchmark_name }}
OSU_BENCHMARK_VERSION={{ osu_benchmark_version }}

module load openmpi
# Run collective benchmark. The collective operations are close to what a real application looks like.
# NOTE: The test is sized for 4 c5n.18xlarge compute nodes (72cpus).
# -np total number of processes to run (72 * 4, all CPUs from 4 nodes)
mpirun -np 288 /shared/openmpi/osu-micro-benchmarks-${OSU_BENCHMARK_VERSION}/mpi/collective/${BENCHMARK_NAME}  > /shared/${BENCHMARK_NAME}.out
