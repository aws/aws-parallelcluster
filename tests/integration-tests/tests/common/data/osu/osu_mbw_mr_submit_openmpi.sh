#!/bin/bash
set -e
module load openmpi

BENCHMARK_NAME={{ benchmark_name }}
OSU_BENCHMARK_VERSION={{ osu_benchmark_version }}
NUM_OF_PROCESSES={{ num_of_processes }}
NUM_OF_PROCESSES_PER_NODE={{ num_of_processes_per_node }}

env

# Run multiple bandwidth/message rate benchmark
# -N: number of processes per node (equal to the number of cores per node; e.g. 48 in a p4d.24xlarge, 96 in a p6-b200.48xlarge)
# -n total number of processes to run (all cores from 2 nodes; e.g. 96 in a p4d.24xlarge, 192 in a p6-b200.48xlarge)
# -x FI_EFA_USE_DEVICE_RDMA=1 Enables RDMA support
mpirun --mca btl_tcp_if_exclude lo -n "${NUM_OF_PROCESSES}" -N "${NUM_OF_PROCESSES_PER_NODE}" -x FI_EFA_USE_DEVICE_RDMA=1 /shared/openmpi/osu-micro-benchmarks-${OSU_BENCHMARK_VERSION}/mpi/pt2pt/${BENCHMARK_NAME} > /shared/${BENCHMARK_NAME}.out
