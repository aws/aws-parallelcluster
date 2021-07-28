#!/bin/bash
set -e

module load openmpi
mpirun -bind-to core /shared/openmpi/osu-micro-benchmarks-5.6.3/mpi/collective/osu_alltoallv -m 64:64 > /shared/osu.out

