#!/usr/bin/env bash
set -e

rm -rf /shared/${1}

module load ${1}
NCCL_BENCHMARKS_VERSION='2.10.0'
NCCL_VERSION='2.7.8-1'
ML_REPO_PKG='nvidia-machine-learning-repo-ubuntu1804_1.0.0-1_amd64.deb'
OFI_NCCL_VERSION='1.1.1'
MPI_HOME=$(which mpirun | awk -F '/bin' '{print $1}')
NVCC_GENCODE="-gencode=arch=compute_80,code=sm_80" # Arch for NVIDIA A100

mkdir -p /shared/${1}

# Install and build nccl from sources
cd /shared/${1}
wget https://github.com/NVIDIA/nccl/archive/v${NCCL_VERSION}.tar.gz
tar zxvf "v${NCCL_VERSION}.tar.gz"
cd nccl-${NCCL_VERSION}
make -j src.build NVCC_GENCODE="${NVCC_GENCODE}"

# Build nccl-tests
cd /shared/${1}
wget https://github.com/NVIDIA/nccl-tests/archive/v${NCCL_BENCHMARKS_VERSION}.tar.gz
tar zxvf "v${NCCL_BENCHMARKS_VERSION}.tar.gz"
cd "nccl-tests-${NCCL_BENCHMARKS_VERSION}/"
NVCC_GENCODE="${NVCC_GENCODE}" make MPI=1 MPI_HOME=${MPI_HOME} NCCL_HOME=/shared/${1}/nccl-${NCCL_VERSION}/build/

wget https://github.com/aws/aws-ofi-nccl/archive/v${OFI_NCCL_VERSION}.tar.gz
tar xvfz v${OFI_NCCL_VERSION}.tar.gz
cd aws-ofi-nccl-${OFI_NCCL_VERSION}
./autogen.sh
./configure --with-libfabric=/opt/amazon/efa --with-cuda=/usr/local/cuda/targets/x86_64-linux/ --with-nccl=/shared/openmpi/nccl-${NCCL_VERSION}/build/ --with-mpi=${MPI_HOME} --prefix /shared/openmpi/ofi-plugin
make
make install
