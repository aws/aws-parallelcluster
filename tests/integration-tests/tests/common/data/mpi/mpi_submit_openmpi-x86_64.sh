#!/bin/bash
set -e

rm -f /shared/mpi.out
module load openmpi-x86_64
# -mca btl ^openib is needed to avoid to have the following warning in the stdout:
# A high-performance Open MPI point-to-point messaging module was unable to find any relevant network interfaces:
# Module: OpenFabrics (openib). Another transport will be used instead, although this may result in lower performance.
export MPIEXEC_TIMEOUT=10
mpirun --map-by ppr:1:node -mca btl ^openib "ring" >> /shared/mpi.out
