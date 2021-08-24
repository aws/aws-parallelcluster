#!/bin/bash
set -e
module load openmpi

BENCHMARK_NAME={{ benchmark_name }}
OSU_BENCHMARK_VERSION={{ osu_benchmark_version }}

# Run multiple bandwidth/message rate benchmark
# NOTE: The test is sized for two P4d compute nodes.
# -N: number of processes per node (48, 1 for each CPU)
# -n total number of processes to run (96, all CPUs from 2 nodes)
# -x FI_EFA_USE_DEVICE_RDMA=1 Enables RDMA support
mpirun --mca btl_tcp_if_exclude lo -n 96 -N 48 -x FI_EFA_USE_DEVICE_RDMA=1 /shared/openmpi/osu-micro-benchmarks-${OSU_BENCHMARK_VERSION}/mpi/pt2pt/${BENCHMARK_NAME} > /shared/${BENCHMARK_NAME}.out