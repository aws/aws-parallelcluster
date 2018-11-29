#!/bin/bash
set -e

echo "Job id: ${AWS_BATCH_JOB_ID}"
echo "Initializing the environment..."

# Starting ssh agents
echo "Starting ssh agents..."
eval `ssh-agent -s` && ssh-add ${SSHDIR}/id_rsa
/usr/sbin/sshd -f /root/.ssh/sshd_config -h /root/.ssh/ssh_host_rsa_key

# mount nfs
echo "Mounting shared file system..."
/parallelcluster/bin/mount_nfs.sh "${MASTER_IP}" "${SHARED_DIR}"

# create hostfile if mnp job
if [ -n "${AWS_BATCH_JOB_NUM_NODES}" ]; then
  echo "Generating hostfile..."
  /parallelcluster/bin/generate_hostfile.sh "${SHARED_DIR}" "${HOME}"
fi

# run the user's script
echo "Starting the job..."
exec "$@"
