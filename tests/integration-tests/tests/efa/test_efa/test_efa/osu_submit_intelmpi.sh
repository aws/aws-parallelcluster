#!/bin/bash
set -e

module load intelmpi
mpirun -np 2 -rr --map-by ppr:1:node /shared/intelmpi/osu-micro-benchmarks-5.6.3/mpi/pt2pt/osu_latency > /shared/osu.out
