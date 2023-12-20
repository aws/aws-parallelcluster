#!/bin/bash
set -ex

# TODO: add efs
for fspath in shared efs; do
    # srun has to be used for whoami because slurm_nss plugin only send user information through srun
    date '+%Y%m%d%H%M%S' > "/$fspath/$(srun whoami)"
done
