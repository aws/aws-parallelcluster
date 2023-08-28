#!/bin/bash

#SBATCH --export=ALL
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=3
#SBATCH --job-name=imb2
#SBATCH --output=runscript.out

module load intelmpi
mpirun -n 6 bash -c 'sleep 300' -npmin 2
