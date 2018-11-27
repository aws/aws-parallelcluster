#!/bin/bash

sleep 30
echo "Hello $1 from $(hostname)"
echo "Hello $1 from $(hostname)" > "/shared/secret_message_for_${1}_by_${AWS_BATCH_JOB_ID}"
