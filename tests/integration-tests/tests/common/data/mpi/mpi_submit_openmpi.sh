#!/bin/bash
set -e

TIMEOUT="$1"

rm -f /shared/mpi.out
# Adding a check to verify IMEX status is UP
if [ -f "/opt/parallelcluster/shared/check_imex_status.sh" ]; then
  srun bash -c "source /opt/parallelcluster/shared/check_imex_status.sh; verify_imex_is_up"
fi

module load openmpi
mpirun --map-by ppr:1:node --timeout "${TIMEOUT}" "ring" >> /shared/mpi.out
