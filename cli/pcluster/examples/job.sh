#!/bin/bash

echo "Starting Job"
/usr/lib64/openmpi/bin/mpirun --allow-run-as-root -np 2 sleep 10
echo $(ls -la)
