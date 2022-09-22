#!/bin/bash
# Test the collective functionality of the Neuron component installed in the ParallelCluster AMI
# This script can work if submitted through Slurm with the following command:
# sbatch --nodes=2 --ntasks-per-node=1 --cpus-per-task=32 neuron-ccl.sh
# or if submitted directly on a single node (SLURM_JOB_NODELIST not set)

cat <<'EOF' >submission-script.sh
#!/bin/bash
set -x

# FIXME remove this repo once packages are public available
TEMPORARY_ARTIFACTS_BUCKET_PATH=s3://aws-parallelcluster-beta/neuron/

# Print available Neuron packages
OS="$(grep "^ID=" /etc/os-release | cut -d"=" -f 2 | xargs)"
case ${OS} in
  ubuntu)
    apt list --installed | grep neuron
    ;;
  amzn)
    rpm -qa | grep neuron
    ;;
  *)
    echo "Unsupported system. Found /etc/os-release ID content: ${OS}"
    exit 1
    ;;
esac

# Identify node name to set the right START_RANK
if [ "${SLURM_NNODES:=1}" == "1" ]; then
  # SLURM_NNODES is not set (no slurm job) or script is executed in a single node
  START_RANK=0
  # retrieve first IP of the list
  HOST_IP=$(hostname -I | cut -d ' ' -f1)
else
  # SLURM_JOB_NODELIST is an array, find first and second node of the array and use number to identify first node.
  NODE_NAME_PREFIX=${SLURM_JOB_NODELIST%-[*}
  NODE1=$(echo $SLURM_JOB_NODELIST | cut -d'[' -f2 | cut -d'-' -f1)
  NODE2=$(echo $SLURM_JOB_NODELIST | cut -d'[' -f2 | cut -d'-' -f2 | tr -d ']')
  HOST_IP=$(scontrol show nodes $NODE_NAME_PREFIX-$NODE1 | grep -oe "NodeAddr=[^ ]*" | cut -d'=' -f2)

  if [ "$(hostname)" == "$NODE_NAME_PREFIX-$NODE1" ]; then
      START_RANK=0
  else
      START_RANK=32
  fi
fi
TOTAL_RANK=$(($SLURM_NNODES*32))

# Download file for simulation (64 in the file name corresponds to the number of ranks hardcoded into the file).
# To use a different number of ranks you need to generate another one:
# python3 inst-sweep/genneffs_nccl.py -n <total-number-of-ranks> --all --output <output-dir>
NEFF_FILE=test_nccl_64r_50allg_int8_393216/0/file.neff
if [[ ! -f $NEFF_FILE ]]; then
  aws s3 cp ${TEMPORARY_ARTIFACTS_BUCKET_PATH}test_nccl_64r_50allg_int8_393216_0_file.neff $NEFF_FILE
fi

# Print eth0 ip
/usr/sbin/ip -br addr show dev eth0 scope global

# Export variables required for neuron-bench
export PATH="/opt/aws/neuron/bin:$PATH"
# Export variables required for EFA
export FI_EFA_USE_DEVICE_RDMA=1
export FI_PROVIDER=efa

NCCL_DEBUG=trace NCCL_DEBUG_SUBSYS=all NCCL_DEBUG_FILE=$(pwd)/nccl_${SLURM_TASK_PID}.log \
NEURON_RT_EXEC_TIMEOUT=10 \
NEURON_RT_ROOT_COMM_ID=$HOST_IP:33666 \
LD_LIBRARY_PATH=/opt/aws/neuron/lib:/opt/amazon/efa/lib64 \
neuron-bench infer --fixed-instance-count 32 --enable-only-latency --work 1 \
  --run-as-cc-neff --minimal-tensor-io --verbose 4 --cc-skip-latencies 5\
  --cc-world-size $TOTAL_RANK --cc-rank-start $START_RANK \
  --summary-percentiles=1,50,99,100 \
  --warmup none $NEFF_FILE | tee output-ccl.txt

EOF

# srun is required to run neuron-bench process on the two nodes
srun bash submission-script.sh