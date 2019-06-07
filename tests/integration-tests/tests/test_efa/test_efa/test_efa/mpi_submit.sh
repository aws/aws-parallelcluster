#!/bin/bash
set -e

module load openmpi
mpirun -N 1 -np 2 "mpi_hello_world" >> /shared/mpi.out
