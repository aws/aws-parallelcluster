#!/bin/bash

JOBID="$1"
OUTPUT=$(scontrol show jobs ${JOBID} | grep StdOut | cut -d '=' -f 2)
start_time=$(tail -n 250 ${OUTPUT} | grep " 501 " | awk '{print $NF}')
end_time=$(tail -n 250 ${OUTPUT} | grep " 600 " | awk '{print $NF}')
elapsed_time=$(python -c "print(${end_time} - ${start_time})")
echo $elapsed_time
