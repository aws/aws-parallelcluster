#!/bin/bash
set -e

module load openmpi
mpirun --map-by ppr:1:node /shared/openmpi/osu-micro-benchmarks-5.4/mpi/pt2pt/osu_latency > /shared/osu.out