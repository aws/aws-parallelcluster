#!/bin/bash
set -e

BENCHMARK_NAME={{ benchmark_name }}
OSU_BENCHMARK_VERSION={{ osu_benchmark_version }}
NUM_OF_PROCESSES={{ num_of_processes }}

module load intelmpi
export I_MPI_DEBUG=10

{% if network_interfaces_count > 1 %}
# Multi NICs instances require extra environment variables.
# See https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start-nccl.html
. /etc/os-release
EFA_PATH=$([ "$ID" == "ubuntu" ] && echo "/opt/amazon/efa/lib" || echo "/opt/amazon/efa/lib64")
export LD_LIBRARY_PATH="${EFA_PATH}:${LD_LIBRARY_PATH}"
export FI_EFA_USE_DEVICE_RDMA=1
{% endif %}

env

# Run collective benchmark. The collective operations are close to what a real application looks like.
# -np total number of processes to run (all vCPUs * N compute nodes), divided by 2 if multithreading is disabled
mpirun -bootstrap=slurm -np ${NUM_OF_PROCESSES} /shared/intelmpi/osu-micro-benchmarks-${OSU_BENCHMARK_VERSION}/mpi/collective/${BENCHMARK_NAME} > /shared/${BENCHMARK_NAME}.out
