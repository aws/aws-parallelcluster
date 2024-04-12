#!/bin/bash
#
# Copyright 2018      Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy
# of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, express or implied. See the License for the specific
# language governing permissions and limitations under the License.
#
#
# Script executed on clusters from parallelcluster-release-check.py.  This
# script attempts to submit two jobs which must complete in 10
# minutes, one of which (hopefully) requires scaling.
#

# Usage:
#   cluster-check.sh {submit | scaledown_check} <scheduler>
#
set -e

slurm_get_slots() {
    local -- ppn i=0
    ppn=$(scontrol show nodes -o | head -n 1 | sed -n -e 's/^.* CPUTot=\([0-9]\+\) .*$/\1/p')
    # wait 15 secs before giving up retrieving the slots per host
    while [ -z "${ppn}" -a $i -lt 15 ]; do
        sleep 1
        i=$((i+1))
        ppn=$(scontrol show nodes -o | head -n 1 | sed -n -e 's/^.* CPUTot=\([0-9]\+\) .*$/\1/p')
    done

    echo ${ppn}
}

submit_launch() {
    # in case the scheduler goes nuts, wrap ourselves in a timeout so
    # there's a bounded completion time
    if test "$CHECK_CLUSTER_SUBPROCESS" = ""; then
        export CHECK_CLUSTER_SUBPROCESS=1
        timeout -s KILL 9m /bin/bash ./cluster-check.sh "$@"
        exit $?
    fi

    scheduler="$2"

    echo "--> scheduler: $scheduler"

    submit_init ${scheduler}

    echo "$(date +%s)" > jobs_start_time

    ${scheduler}_submit
    echo "Jobs submitted successfully"
}

submit_init() {
    # we submit 3 1-node jobs, each of which are a sleep.
    # The whole thing has to run in 9 minutes (higher of the three sleep times + buffer),
    # or the kill in submit_launch will fail the job, which means that the jobs must run at the same time.
    # The initial cluster is 1 nodes, so we'll need to scale up 2 further nodes simultaneously
    # and bootstrap in less than 7 minutes and run the job that needs 105 seconds
    # in order for the test to succeed.

    # job1: 7m45s
    export _sleepjob1=465
    # job2: 1m45s
    export _sleepjob2=105
    # job3: 1m45s
    export _sleepjob3=105

    scheduler=$1
    export _ppn=$(${scheduler}_get_slots)
    if [ -z "${_ppn}" ]; then
        >&2 echo "The number of slots per instance couldn't be retrieved, no compute nodes available in ${scheduler} cluster"
        exit 1
    fi
}

slurm_submit() {
    cat > job1.sh <<EOF
#!/bin/bash
srun sleep ${_sleepjob1}
echo "\$(date +%s)" > job1.done
EOF
    cat > job2.sh <<EOF
#!/bin/bash
srun sleep ${_sleepjob2}
echo "\$(date +%s)" > job2.done
EOF

    cat > job3.sh <<EOF
#!/bin/bash
srun sleep ${_sleepjob3}
echo "\$(date +%s)" > job3.done
EOF

    chmod +x job1.sh job2.sh job3.sh
    rm -f job1.done job2.done job3.done

    sbatch -N 1 -n ${_ppn} ./job1.sh
    sbatch -N 1 -n ${_ppn} ./job2.sh
    sbatch -N 1 -n ${_ppn} ./job3.sh
}

scaledown_check_launch() {
    # bounded completion time
    if test "$CHECK_CLUSTER_SUBPROCESS" = ""; then
        export CHECK_CLUSTER_SUBPROCESS=1
        timeout -s KILL 5m /bin/bash ./cluster-check.sh "$@"
        exit $?
    fi

    scheduler="$2"

    echo "--> scheduler: $scheduler"

    scaledown_complete=0
    while test $scaledown_complete = 0 ; do
        ${scheduler}_scaledown_check
        sleep 10
    done
    echo "Scaledown successful"
}

has_zero_active_instances(){
    instances=$1
    if [[ ${instances} ]]; then
        echo "instances have not scaled down yet"
        scaledown_complete=0
    else
        echo "instances have scaled down; exiting"
        scaledown_complete=1
    fi
}

slurm_scaledown_check() {
    has_zero_active_instances $(sinfo --noheader | awk '$4 != "0"')
}

main() {
    case "$1" in
        submit)
            submit_launch "$@"
            ;;
        scaledown_check)
            scaledown_check_launch "$@"
            ;;
        *)
            echo "!! Unknown command $1 !!"
            exit 1
            ;;
    esac
}

main "$@"
