#!/bin/bash
# Test the basic functionality of the Neuron component installed in the ParallelCluster AMI

# Print available Neuron packages
OS="$(grep "^ID=" /etc/os-release | cut -d"=" -f 2 | xargs)"
case ${OS} in
  ubuntu)
    apt list --installed | grep neuron
    USER=ubuntu
    ;;
  amzn)
    rpm -qa | grep neuron
    USER=ec2-user
    ;;
  *)
    echo "Unsupported system. Found /etc/os-release ID content: ${OS}"
    exit 1
    ;;
esac

# Create python scripts required for the tests
cat <<EOF >allreduce_launch.py
import os
import torch_xla.core.xla_model as xm
import torch
import torch.distributed as dist
from torch_xla.distributed import xla_backend

#os.environ["NEURON_RT_LOG_LEVEL"] = "INFO"
#os.environ["NEURON_RT_LOG_LOCATION"] = "syslog"
#os.environ["NCCL_DEBUG"] = "ERROR"
#os.environ["NCCL_DEBUG_SUBSYS"] = "ALL"


def _mp_fn():
    dist.init_process_group('xla')
    world_size = xm.xrt_world_size()
    device = xm.xla_device()

    if world_size > 0:
        ones = torch.ones((2, 3))
        xones = ones.to(device)
        print("running all reduce")
        result = xm.all_reduce(xm.REDUCE_SUM, xones)
        result_cpu = result.cpu()
        expected = torch.ones((2,3))*world_size
        assert expected.allclose(result_cpu)
        print(result_cpu)
        print('PASS')


if __name__ == '__main__':
    print(
        'master_port:{}, master_addr:{}, rank:{}, local_rank:{}, size:{}'.format(
            os.environ['MASTER_PORT'],
            os.environ['MASTER_ADDR'],
            os.environ['RANK'],
            os.environ['LOCAL_RANK'],
            os.environ['WORLD_SIZE'],
        )
    )

    _mp_fn()
EOF


cat <<'EOF' >test_launch.py
import os
import subprocess


def test_local_launch_allreduce():
    # This test launches a two phase launcher, spawns two processes which
    # in turn launch more processes. This uses pytorch distributed.launch utility along with ptxrt bridge
    cmd = "torchrun --nproc_per_node=$PROC_PER_NODE --nnodes=1 allreduce_launch.py "

    new_env0 = os.environ.copy()
    new_env0['PROC_PER_NODE'] = '2'

    proc0 = subprocess.Popen(cmd, env=new_env0, shell=True)

    return_code = proc0.wait()
    assert return_code == 0
EOF

# Activate virtual environment created by neuron-installation.sh and run the test
# We expect to find PASSED word at the end of the output
source /home/$USER/aws_neuron_venv_pytorch/bin/activate
pytest test_launch.py -vxs | tee output-allreduce.txt
