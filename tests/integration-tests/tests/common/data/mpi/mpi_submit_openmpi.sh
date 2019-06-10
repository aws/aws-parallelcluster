#!/bin/bash
set -e

module load openmpi
mpirun --map-by ppr:1:node "mpi_hello_world" >> /shared/mpi.out
