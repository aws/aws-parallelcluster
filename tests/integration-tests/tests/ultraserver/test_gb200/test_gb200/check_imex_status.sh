#!/bin/bash


# Maximum number of attempts
MAX_ATTEMPTS=10

# Function to run the command and check status
verify_imex_is_up() {
    local command="/usr/bin/nvidia-imex-ctl -N -j"
    local file_prefix="result"

    for ((i=1; i<=MAX_ATTEMPTS; i++)); do
        echo "Attempt $i for IMEX"

        command_output=$(${command} 2>/dev/null)
        # Check if the status is UP
        if echo "$command_output" | grep -q " \"status\": \"UP\""; then
            echo "IMEX is UP. Exiting loop."
            echo "writing the output in ${file_prefix}_${SLURM_JOB_ID}_$(hostname).out"
            echo "$command_output" > ${file_prefix}_${SLURM_JOB_ID}_$(hostname).out 2> ${file_prefix}_${SLURM_JOB_ID}_$(hostname).err
            break
        elif [ $i -eq $MAX_ATTEMPTS ]; then
            echo "Max attempts reached. Status is not UP."
        else
            echo "IMEX is not UP. Retrying..."
            sleep 30  # Wait for 30 seconds before the next attempt
        fi
    done
}
