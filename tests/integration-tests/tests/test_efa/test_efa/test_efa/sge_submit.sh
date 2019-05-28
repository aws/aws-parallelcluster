#!/bin/bash
#$ -pe mpi 144

module load openmpi
mpirun -N 1 -np 2 "mpi_hello_world"