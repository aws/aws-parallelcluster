#!/bin/bash
echo "ip container: $(/sbin/ip -o -4 addr list eth0 | awk '{print $4}' | cut -d/ -f1)"
echo "ip host: $(curl -s "http://169.254.169.254/latest/meta-data/local-ipv4")"

if [[ "${AWS_BATCH_JOB_NODE_INDEX}" -eq  "${AWS_BATCH_JOB_MAIN_NODE_INDEX}" ]]; then
    echo "Compiling..."
    /usr/lib64/openmpi/bin/mpicc -o mpi_hello_world /shared/mpi_hello_world.c

    echo "Hello I'm the main node! I run the mpi job!"
    /usr/lib64/openmpi/bin/mpirun --mca btl_tcp_if_include eth0 --allow-run-as-root --machinefile "${HOME}/hostfile" mpi_hello_world
else
    echo "Hello I'm a compute note! I let the main node orchestrate the mpi execution!"
    # Since mpi orchestration happens on the main node, we need to make sure the containers representing the compute
    # nodes are not terminated. A simple trick is to run an infinite sleep.
    # All compute nodes will be terminated by Batch once the main node exits.
    sleep infinity
fi
