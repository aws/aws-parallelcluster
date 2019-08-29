#!/bin/bash
set -e

module load openmpi
chmod +x ${HOME}/install_clck.sh
mpirun --map-by ppr:1:node ${HOME}/install_clck.sh
