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
# script attempts to submit two jobs which must complete in 30
# minutes, one of which (hopefully) requires scaling (note that
# scaling is currently not tested on Torque, because it's too big of a
# pain to determine how many slots per node are on a Torque compute
# node from the master node).
#

# in case the scheduler goes nuts, wrap ourselves in a timeout so
# there's a bounded completion time
if test "$CHECK_CLUSTER_SUBPROCESS" = ""; then
   export CHECK_CLUSTER_SUBPROCESS=1
   timeout -s KILL 10m /bin/bash ./cluster-check.sh "$@"
   exit $?
fi

scheduler="$1"

echo "--> scheduler: $scheduler"

set -e

# we submit 2 2-node jobs, each of which are a sleep for 16 minutes.
# The whole thing has to run in 30 minutes, or the kill above will
# fail the job, which means that the jobs must run at the same time.
# The initial cluster is 2 nodes, so we'll need to scale up 2 nodes in
# less than 10 minutes in order for the test to succeed.

if test "$scheduler" = "slurm" ; then
    cat > job1.sh <<EOF
#!/bin/bash
srun sleep 360
touch job1.done
EOF
    cat > job2.sh <<EOF
#!/bin/bash
srun sleep 360
touch job2.done
EOF

    chmod +x job1.sh job2.sh
    rm -f job1.done job2.done

    sbatch -N 1 ./job1.sh
    sbatch -N 1 ./job2.sh

elif test "$scheduler" = "sge" ; then
    # get the slots per node count of the first real node (one with a
    # architecture type of lx-?), so that we can reserve an enitre
    # node's worth of slots at a time.
    ppn=` qhost | grep 'lx-' | head -n 1 | sed -n -e 's/[^[:space:]]*[[:space:]]\+[^[:space:]]*[[:space:]]\+\([0-9]\+\).*/\1/p'`
    count=$((ppn))

    cat > job1.sh <<EOF
#!/bin/bash
#$ -pe mpi $count
#$ -R y

sleep 360
touch job1.done
EOF
    cat > job2.sh <<EOF
#!/bin/bash
#$ -pe mpi $count
#$ -R y

sleep 360
touch job2.done
EOF

    chmod +x job1.sh job2.sh
    rm -f job1.done job2.done

    qsub ./job1.sh
    qsub ./job2.sh

elif test "$scheduler" = "torque" ; then
    cat > job1.sh <<EOF
#!/bin/bash
sleep 360
touch job1.done
EOF
    cat > job2.sh <<EOF
#!/bin/bash
sleep 360
touch job2.done
EOF

    chmod +x job1.sh job2.sh
    rm -f job1.done job2.done

    qsub -l nodes=1:ppn=1 ./job1.sh
    qsub -l nodes=1:ppn=1 ./job2.sh

else
    echo "!! Unknown scheduler $scheduler !!"
    exit 1
fi

done=0
while test $done = 0 ; do
    if test -f job1.done -a -f job2.done; then
        done=1
    else
        sleep 1
    fi
done

exit 0
