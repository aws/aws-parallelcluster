#!/bin/bash

#SBATCH --export=ALL
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=3
#SBATCH --job-name=imb2
#SBATCH --output=runscript.out

module load intelmpi
mpirun -n 6 IMB-MPI1 Alltoall -npmin 2
