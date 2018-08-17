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
# Script executed on clusters from cfncluster-release-check.py.  This
# script attempts to submit two jobs which must complete in 10
# minutes, one of which (hopefully) requires scaling (note that
# scaling is currently not tested on Torque, because it's too big of a
# pain to determine how many slots per node are on a Torque compute
# node from the master node).
#

# Usage:
#   cluster-check.sh {submit | scaledown_check} <scheduler>
#
set -e

sge_get_slots() {
    local -- ppn i=0
    ppn=$(qhost | grep 'lx-' | head -n 1 | sed -n -e 's/[^[:space:]]*[[:space:]]\+[^[:space:]]*[[:space:]]\+\([0-9]\+\).*/\1/p')
    # wait 15 secs before giving up retrieving the slots per host
    while [ -z "${ppn}" -a $i -lt 15 ]; do
        sleep 1
        i=$((i+1))
        ppn=$(qhost | grep 'lx-' | head -n 1 | sed -n -e 's/[^[:space:]]*[[:space:]]\+[^[:space:]]*[[:space:]]\+\([0-9]\+\).*/\1/p')
    done

    echo ${ppn}
}

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

torque_get_slots() {
    local -- chost ppn i=0

    chost=$({ pbsnodes -l free ; pbsnodes -l job-exclusive; } | head -n 1 | cut -d ' ' -f1)
    # wait 15 secs before giving up retrieving the slots per host
    while [ -z "${chost}" -a $i -lt 15 ]; do
        sleep 1
        i=$((i+1))
        chost=$({ pbsnodes -l free ; pbsnodes -l job-exclusive; } | head -n 1 | cut -d ' ' -f1)
    done
    [ -n "${chost}" ] && ppn=$(pbsnodes ${chost} | tr -d '\t ' | sed -n '/np=/{s/^np=\([0-9]\+\)/\1/;p;}')

    echo ${ppn}
}

submit_launch() {
    # in case the scheduler goes nuts, wrap ourselves in a timeout so
    # there's a bounded completion time
    if test "$CHECK_CLUSTER_SUBPROCESS" = ""; then
        export CHECK_CLUSTER_SUBPROCESS=1
        timeout -s KILL 10m /bin/bash ./cluster-check.sh "$@"
        exit $?
    fi

    scheduler="$2"

    echo "--> scheduler: $scheduler"

    submit_init ${scheduler}

    ${scheduler}_submit

    done=0
    while test $done = 0 ; do
        if test -f job1.done -a -f job2.done; then
            done=1
        else
            sleep 1
        fi
    done
}

submit_init() {
    # we submit 2 1-node jobs, each of which are a sleep.
    # The whole thing has to run in 10 minutes, or the kill above will
    # fail the job, which means that the jobs must run at the same time.
    # The initial cluster is 1 nodes, so we'll need to scale up 1 further node in
    # less than 8 minutes in order for the test to succeed.

    # job1: 8m30s
    export _sleepjob1=510
    # job2: 2m
    export _sleepjob2=120

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
touch job1.done
EOF
    cat > job2.sh <<EOF
#!/bin/bash
srun sleep ${_sleepjob2}
touch job2.done
EOF

    chmod +x job1.sh job2.sh
    rm -f job1.done job2.done

    sbatch -N 1 -n ${_ppn} ./job1.sh
    sbatch -N 1 -n ${_ppn} ./job2.sh
}

sge_submit() {
    count=$((_ppn))

    cat > job1.sh <<EOF
#!/bin/bash
#$ -pe mpi $count
#$ -R y

sleep ${_sleepjob1}
touch job1.done
EOF
    cat > job2.sh <<EOF
#!/bin/bash
#$ -pe mpi $count
#$ -R y

sleep ${_sleepjob2}
touch job2.done
EOF

    chmod +x job1.sh job2.sh
    rm -f job1.done job2.done

    qsub ./job1.sh
    qsub ./job2.sh
}

torque_submit() {
    cat > job1.sh <<EOF
#!/bin/bash
sleep ${_sleepjob1}
touch job1.done
EOF
    cat > job2.sh <<EOF
#!/bin/bash
sleep ${_sleepjob2}
touch job2.done
EOF

    chmod +x job1.sh job2.sh
    rm -f job1.done job2.done

    echo "qsub -l nodes=1:ppn=${_ppn} ./job1.sh"
    qsub -l nodes=1:ppn=${_ppn} ./job1.sh
    echo "qsub -l nodes=1:ppn=${_ppn} ./job2.sh"
    qsub -l nodes=1:ppn=${_ppn} ./job2.sh
}

scaledown_check_launch() {
    # bounded completion time
    if test "$CHECK_CLUSTER_SUBPROCESS" = ""; then
        export CHECK_CLUSTER_SUBPROCESS=1
        timeout -s KILL 3m /bin/bash ./cluster-check.sh "$@"
        exit $?
    fi

    scheduler="$2"

    echo "--> scheduler: $scheduler"

    done=0
    while test $done = 0 ; do
        ${scheduler}_scaledown_check
        if [[ $? == 0 ]]; then
            done=1
        else
            sleep 10
        fi
    done
}

has_zero_active_instances(){
    instances=$1
    if [[ ${instances} ]]; then
        echo "instances have not scaled down yet"
        return 1
    else
        echo "instances have scaled down; exiting"
        return 0
    fi
}

slurm_scaledown_check() {
    has_zero_active_instances $(sinfo --noheader | awk '$4 != "0"')
    return $?
}

sge_scaledown_check() {
    has_zero_active_instances $(qhost | grep ip-)
    return $?
}

torque_scaledown_check() {
    has_zero_active_instances $(pbsnodes | grep status)
    return $?
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
