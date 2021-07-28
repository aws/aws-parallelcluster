#!/bin/bash
set -e

module load intelmpi
mpirun -bind-to core /shared/intelmpi/osu-micro-benchmarks-5.6.3/mpi/collective/osu_alltoall -m 64:64 > /shared/osu.out
mpirun -bind-to core  /shared/intelmpi/osu-micro-benchmarks-5.6.3/mpi/collective/osu_igatherv -m 4:4 >> /shared/osu.out
