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
/parallelcluster/bin/mount_nfs.sh "${PCLUSTER_HEAD_NODE_IP}" "/home"

# create if not exists hidden pcluster folder
PCLUSTER_HIDDEN_FOLDER="/home/.pcluster/"
if [ ! -d "${PCLUSTER_HIDDEN_FOLDER}" ]; then
  echo "Creating ${PCLUSTER_HIDDEN_FOLDER}"
  mkdir "${PCLUSTER_HIDDEN_FOLDER}"
fi

echo "Mounting shared file system..."
ebs_shared_dirs=$(echo "${PCLUSTER_SHARED_DIRS}" | tr "," " ")

for ebs_shared_dir in ${ebs_shared_dirs}
do
  if [[ ${ebs_shared_dir} != "NONE" ]]; then
    # mount nfs
    /parallelcluster/bin/mount_nfs.sh "${PCLUSTER_HEAD_NODE_IP}" "${ebs_shared_dir}"
  fi
done

ebs_arr=($ebs_shared_dirs)

# mount EFS via nfs
IFS=',' read -r -a efs_ids <<< "${PCLUSTER_EFS_FS_IDS}"
IFS=',' read -r -a efs_shared_dirs <<< "${PCLUSTER_EFS_SHARED_DIRS}"
for i in "${!efs_ids[@]}"; do
  /parallelcluster/bin/mount_efs.sh "${efs_ids[i]}" "${PCLUSTER_AWS_REGION}" "${efs_shared_dirs[i]}"
done

# mount RAID via nfs
if [[ ${PCLUSTER_RAID_SHARED_DIR} != "NONE" ]]; then
  /parallelcluster/bin/mount_nfs.sh "${PCLUSTER_HEAD_NODE_IP}" "${PCLUSTER_RAID_SHARED_DIR}"
fi

# create hostfile if mnp job
if [ -n "${AWS_BATCH_JOB_NUM_NODES}" ]; then
  /parallelcluster/bin/generate_hostfile.sh "${PCLUSTER_HIDDEN_FOLDER}" "${HOME}"
fi

# run the user's script
echo "Starting the job..."
exec "$@"
