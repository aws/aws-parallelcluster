#!/bin/bash
set -e

echo "Executing $0"

PROLOG_NVIDIA_IMEX=/opt/slurm/etc/scripts/prolog.d/{{ prolog_filename }}
aws s3 cp s3://{{ bucket_name }}/{{ prolog_filename }} ${PROLOG_NVIDIA_IMEX}
chmod 0755 ${PROLOG_NVIDIA_IMEX}

CHECK_IMEX_STATUS=/opt/parallelcluster/shared/{{ check_imex_status_filename }}
aws s3 cp s3://{{ bucket_name }}/{{ check_imex_status_filename }} ${CHECK_IMEX_STATUS}
chmod 0755 ${CHECK_IMEX_STATUS}

JOB_SCRIPT=/opt/parallelcluster/shared/{{ job_filename }}
aws s3 cp s3://{{ bucket_name }}/{{ job_filename }} ${JOB_SCRIPT}
chmod 0755 ${JOB_SCRIPT}