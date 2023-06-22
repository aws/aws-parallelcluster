#!/bin/bash
# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.

PIDS=($(pgrep supervisord$))
for PID in "${PIDS[@]}"
do
    CMD_LINE=($(ps -p ${PID} -o args --no-headers))
    # CMD_LINE is in the form
    # /opt/parallelcluster/shared/path/pyenv/versions/3.9.9/envs/some_virtualenv/bin/python3.9 /opt/parallelcluster/shared/path/pyenv/versions/3.9.9/envs/some_virtualenv/bin/supervisord -n -c /opt/parallelcluster/some_path/supervisord.conf
    if ${CMD_LINE[0]} $(dirname ${CMD_LINE[1]})/supervisorctl -c ${CMD_LINE[4]} status clustermgtd &>/dev/null; then
        ${CMD_LINE[0]} $(dirname ${CMD_LINE[1]})/supervisorctl -c ${CMD_LINE[4]} start clustermgtd
    fi
done
