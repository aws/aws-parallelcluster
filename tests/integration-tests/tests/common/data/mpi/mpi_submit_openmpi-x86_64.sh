#!/bin/bash
set -e

module load openmpi-x86_64
mpirun --map-by ppr:1:node -mca btl ^openib "mpi_hello_world" >> /shared/mpi.out
