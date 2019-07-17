#!/bin/bash
set -e

rm -f /shared/mpi.out
module load openmpi
mpirun --map-by ppr:1:node "mpi_hello_world" >> /shared/mpi.out
