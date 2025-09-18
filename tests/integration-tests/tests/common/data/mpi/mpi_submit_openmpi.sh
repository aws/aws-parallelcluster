#!/bin/bash
set -e

TIMEOUT="$1"

rm -f /shared/mpi.out
module load openmpi
mpirun --map-by ppr:1:node --timeout "${TIMEOUT}" "ring" >> /shared/mpi.out
