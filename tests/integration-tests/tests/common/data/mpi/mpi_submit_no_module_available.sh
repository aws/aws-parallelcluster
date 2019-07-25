#!/bin/bash
set -e

rm -f /shared/mpi.out
# -mca btl ^openib is needed to avoid to have the following warning in the stdout:
# A high-performance Open MPI point-to-point messaging module was unable to find any relevant network interfaces:
# Module: OpenFabrics (openib). Another transport will be used instead, although this may result in lower performance.
mpirun --map-by ppr:1:node -mca btl ^openib "mpi_hello_world" >> /shared/mpi.out
