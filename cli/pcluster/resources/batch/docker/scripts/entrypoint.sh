#!/bin/bash
set -e

echo "Job id: ${AWS_BATCH_JOB_ID}"
echo "Initializing the environment..."

# Starting ssh agents
echo "Starting ssh agents..."
eval $(ssh-agent -s) && ssh-add ${SSHDIR}/id_rsa
/usr/sbin/sshd -f /root/.ssh/sshd_config -h /root/.ssh/ssh_host_rsa_key

# get private Master IP
_master_ip="$(aws --region "${PCLUSTER_AWS_REGION}" cloudformation describe-stacks --stack-name "${PCLUSTER_STACK_NAME}" --query "Stacks[0].Outputs[?OutputKey=='MasterPrivateIP'].OutputValue" --output text)"
if [[ -z "${_master_ip}" ]]; then
    echo "Error getting Master IP"
    exit 1
fi

# mount nfs
echo "Mounting shared file system..."
/parallelcluster/bin/mount_nfs.sh "${_master_ip}" "${PCLUSTER_SHARED_DIR}"
/parallelcluster/bin/mount_nfs.sh "${_master_ip}" "/home"

# mount EFS via nfs
if [[ "${PCLUSTER_EFS_FS_ID}" != "NONE" ]] && [[ ! -z "${PCLUSTER_AWS_REGION}" ]] && [[ "${PCLUSTER_EFS_SHARED_DIR}" != "NONE" ]]; then
  /parallelcluster/bin/mount_efs.sh "${PCLUSTER_EFS_FS_ID}" "${PCLUSTER_AWS_REGION}" "${PCLUSTER_EFS_SHARED_DIR}"
fi

# create hostfile if mnp job
if [[ -n "${AWS_BATCH_JOB_NUM_NODES}" ]]; then
  echo "Generating hostfile..."
  /parallelcluster/bin/generate_hostfile.sh "${PCLUSTER_SHARED_DIR}" "${HOME}"
fi

# run the user's script
echo "Starting the job..."
exec "$@"
