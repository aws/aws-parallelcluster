#!/bin/bash
set -e

echo "Executing $0"

PROLOG_NVIDIA_IMEX=/opt/slurm/etc/scripts/prolog.d/{{ prolog_filename }}
aws s3 cp s3://{{ bucket_name }}/{{ prolog_filename }} ${PROLOG_NVIDIA_IMEX}
chmod 0755 ${PROLOG_NVIDIA_IMEX}

JOB_SCRIPT=/opt/parallelcluster/shared/{{ job_filename }}
aws s3 cp s3://{{ bucket_name }}/{{ job_filename }} ${JOB_SCRIPT}
chmod 0755 ${JOB_SCRIPT}