#!/bin/bash
set -ex

# TODO: add efs
for fspath in shared ebs; do
    # srun has to be used for whoami because slurm_nss plugin only send user information through srun
    date '+%Y%m%d%H%M%S' > "/$fspath/$(srun whoami)"
done

BENCHMARK_NAME=osu_barrier
OSU_BENCHMARK_VERSION=5.7.1

module load openmpi
# Run collective benchmark. The collective operations are close to what a real application looks like.
# NOTE: The test is sized for 4 compute nodes.
# -np total number of processes to run (all CPUs * 4 nodes)
mpirun \
    > /shared/"$(date '+%Y%m%d%H%M%S')-$(srun whoami)-${BENCHMARK_NAME}".out \
    /shared/openmpi/osu-micro-benchmarks-${OSU_BENCHMARK_VERSION}/mpi/collective/${BENCHMARK_NAME}  
