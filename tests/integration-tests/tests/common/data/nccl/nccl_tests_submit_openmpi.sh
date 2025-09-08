#!/bin/bash
#SBATCH --nodes=2
#SBATCH --exclusive

module load openmpi
NCCL_VERSION='2.27.7-1'
NCCL_BENCHMARKS_VERSION='2.16.7'

. /etc/os-release
if [[ $ID==rhel || $ID==rocky ]]; then
  OFI_PATH="/shared/openmpi/ofi-plugin/lib/"
else
  OFI_PATH=$(cat /etc/ld.so.conf.d/100_ofinccl.conf)
fi

mpirun \
-x FI_PROVIDER="efa" \
-x FI_EFA_USE_DEVICE_RDMA=1 \
-x LD_LIBRARY_PATH=/shared/openmpi/nccl-${NCCL_VERSION}/build/lib/:${OFI_PATH}:$LD_LIBRARY_PATH \
-x RDMAV_FORK_SAFE=1 \
-x NCCL_ALGO=ring \
-x NCCL_DEBUG=WARNING \
-x NCCL_PROTO=simple \
--mca pml ^cm --mca btl tcp,self --mca btl_tcp_if_exclude lo,docker0 --bind-to none \
/shared/openmpi/nccl-tests-${NCCL_BENCHMARKS_VERSION}/build/all_reduce_perf -b 8 -e 1G -f 2 -g 1 -c 1 -n 100 > /shared/nccl_tests.out
