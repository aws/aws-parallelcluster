#!/bin/bash

echo "custom_action script has $# arguments"
for arg in "$@"
do
    echo "executing ${arg}"
    "${arg}" || echo "failed to execute ${arg}"
done
