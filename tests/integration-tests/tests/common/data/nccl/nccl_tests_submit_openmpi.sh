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

#  -x NCCL_ALGO=ring is not needed after NCCL 2.12. NCCL autodetects which ALGO (ring or tree) to use
# -x FI_EFA_USE_DEVICE_RDMA=1 is not needed from aws nccl pfi plugin version v1.6.0
# -x NCCL_SOCKET_FAMILY=AF_INET forces NCCL to use IPv4. On Ubuntu 24 with p6-b200, without this parameter, NCCL hangs on IPv6, which is not supported by ParallelCluster
mpirun \
-x LD_LIBRARY_PATH=/shared/openmpi/nccl-${NCCL_VERSION}/build/lib/:${OFI_PATH}:$LD_LIBRARY_PATH \
-x NCCL_DEBUG=WARNING \
-x NCCL_TESTS_SPLIT_MASK=0x0 \
-x NCCL_SOCKET_FAMILY=AF_INET \
-x RDMAV_FORK_SAFE=1 \
--bind-to none \
/shared/openmpi/nccl-tests-${NCCL_BENCHMARKS_VERSION}/build/all_reduce_perf -b 1024 -e 8G -f 2 -g 1 -c 1 > /shared/nccl_tests.out
