#!/bin/bash
set -e

BENCHMARK_NAME={{ benchmark_name }}
OSU_BENCHMARK_VERSION={{ osu_benchmark_version }}

module load intelmpi
export I_MPI_DEBUG=10

{% if network_interfaces_count > 1 %}
# Multi NICs instances require extra environment variables.
# See https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start-nccl.html
. /etc/os-release
EFA_PATH=$([ "$ID" == "ubuntu" ] && echo "/opt/amazon/efa/lib" || echo "/opt/amazon/efa/lib64")
export LD_LIBRARY_PATH="/opt/amazon/efa/lib:${LD_LIBRARY_PATH}"
export FI_EFA_USE_DEVICE_RDMA=1
{% endif %}

env

mpirun -bootstrap=slurm -np 2 -ppn 1 /shared/intelmpi/osu-micro-benchmarks-${OSU_BENCHMARK_VERSION}/mpi/pt2pt/${BENCHMARK_NAME} > /shared/${BENCHMARK_NAME}.out
