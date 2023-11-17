#!/bin/bash
# ntasks = Nodes * (vCPUs / 2); vCPUs are cut in a half because multithreading is disabled
#          Example: using compute nodes c5n.18xlarge with 72 vCPUS, if we want to use only one node we must set this value to 36.
# The command /shared/STAR-CCM+/16.02.008/STAR-CCM+16.02.008/star/bin/starccm+ should be from an installation made for the user that will run the simulation

#SBATCH --job-name=starccm
#SBATCH --output=%x_%j.out
#SBATCH --exclusive
#SBATCH --no-requeue
#module unload libfabric-aws
#export I_MPI_OFI_LIBRARY_INTERNAL=0
#ulimit -s unlimited
module load intelmpi
export FI_EFA_FORK_SAFE=1
export I_MPI_OFI_LIBRARY_INTERNAL=0
module load libfabric-aws
export I_MPI_FABRICS=shm:ofi
export I_MPI_OFI_PROVIDER=efa
export I_MPI_DEBUG=10
export FI_EFA_FORK_SAFE=1

export I_MPI_HYDRA_BOOTSTRAP="slurm"

SHARED_DIR="/shared"

STARCCM="${SHARED_DIR}/STAR-CCM+/18.02.008/STAR-CCM+18.02.008/star/bin/starccm+"
SIM_FILE="${SHARED_DIR}/lemans_poly_17m.amg@00500.sim"

podkey="$1"
licpath="$2"

${STARCCM} \
        -bs slurm \
        -power \
        -batch \
        -podkey "${podkey}" \
        -licpath "${licpath}" \
        -mpi intel \
        -xsystemlibfabric -ldlibpath /opt/amazon/efa/lib64 \
        -fabric OFI -vvv \
        ${SIM_FILE}
