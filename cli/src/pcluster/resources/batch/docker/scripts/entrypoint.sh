#!/bin/bash
set -e

echo "Job id: ${AWS_BATCH_JOB_ID}"
echo "Initializing the environment..."

# Starting ssh agents
echo "Starting ssh agents..."
eval $(ssh-agent -s) && ssh-add ${SSHDIR}/id_rsa
/usr/sbin/sshd -f /root/.ssh/sshd_config -h /root/.ssh/ssh_host_rsa_key

# mount nfs
echo "Mounting /home..."
/parallelcluster/bin/mount_nfs.sh "${PCLUSTER_MASTER_IP}" "/home"

echo "Mounting shared file system..."
ebs_shared_dirs=$(echo "${PCLUSTER_SHARED_DIRS}" | tr "," " ")

for ebs_shared_dir in ${ebs_shared_dirs}
do
  if [[ ${ebs_shared_dir} != "NONE" ]]; then
    # mount nfs
    /parallelcluster/bin/mount_nfs.sh "${PCLUSTER_MASTER_IP}" "${ebs_shared_dir}"
  fi
done

ebs_arr=($ebs_shared_dirs)
first_ebs_shared_dir=${ebs_arr[0]}

# mount EFS via nfs
if [[ "${PCLUSTER_EFS_FS_ID}" != "NONE" ]] && [[ ! -z "${PCLUSTER_AWS_REGION}" ]] && [[ "${PCLUSTER_EFS_SHARED_DIR}" != "NONE" ]]; then
  /parallelcluster/bin/mount_efs.sh "${PCLUSTER_EFS_FS_ID}" "${PCLUSTER_AWS_REGION}" "${PCLUSTER_EFS_SHARED_DIR}"
fi

# mount RAID via nfs
if [[ ${PCLUSTER_RAID_SHARED_DIR} != "NONE" ]]; then
  /parallelcluster/bin/mount_nfs.sh "${PCLUSTER_MASTER_IP}" "${PCLUSTER_RAID_SHARED_DIR}"
fi

# create hostfile if mnp job
if [ -n "${AWS_BATCH_JOB_NUM_NODES}" ]; then
  /parallelcluster/bin/generate_hostfile.sh "${first_ebs_shared_dir}" "${HOME}"
fi

# run the user's script
echo "Starting the job..."
exec "$@"
