#!/bin/bash
set -e

echo "Starting Job ${AWS_BATCH_JOB_ID}"

# mount nfs
/parallelcluster/bin/mount_nfs.sh "${MASTER_IP}" "${SHARED_DIR}"

# create hostfile if mnp job
if [ -n "${AWS_BATCH_JOB_NUM_NODES}" ]; then
  /parallelcluster/bin/generate_hostfile.sh "${SHARED_DIR}" "${HOME}"
fi

# run the user's script
exec "$@"
