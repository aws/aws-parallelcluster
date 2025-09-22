#!/bin/bash


# Maximum number of attempts
MAX_ATTEMPTS=10

# Function to run the command and check status
verify_imex_is_up() {
    local command="/usr/bin/nvidia-imex-ctl -N -j"
    local file_name="result_${SLURM_JOB_ID}_$(hostname)"

    for ((i=1; i<=MAX_ATTEMPTS; i++)); do
        echo "Attempt $i/$MAX_ATTEMPTS for IMEX"

        command_output=$(${command})
        echo "Output from IMEX for $i/$MAX_ATTEMPTS attempt: $command_output"
        # Check if the status is UP
        if echo "$command_output" | jq -r '.status' ; then
            echo "IMEX is UP. Exiting loop."
            echo "writing the output in ${file_name}.out"
            echo "$command_output" > ${file_name}.out 2> ${file_name}.err
            break
        elif [ $i -eq $MAX_ATTEMPTS ]; then
            echo "Max attempts reached. Status is not UP."
        else
            echo "IMEX is not UP. Retrying after 30 seconds..."
            sleep 30  # Wait for 30 seconds before the next attempt
        fi
    done
}
