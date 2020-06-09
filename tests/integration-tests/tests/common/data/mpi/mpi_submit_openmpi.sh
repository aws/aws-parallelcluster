#!/bin/bash
set -e

rm -f /shared/mpi.out
module load openmpi
export MPIEXEC_TIMEOUT=10  # 10 second timeout
mpirun --mca btl_base_warn_component_unused 0 --map-by ppr:1:node "ring" >> /shared/mpi.out
