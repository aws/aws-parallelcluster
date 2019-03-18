.. _awsbatchcli:

######################################
AWS ParallelCluster Batch CLI Commands
######################################

The AWS ParallelCluster Batch CLI commands will be automatically installed on the AWS ParallelCluster Master Node
when the selected scheduler is ``awsbatch.``

The CLI uses AWS Batch APIs to mirror traditional scheduler commands that are used to to submit, manage, and monitor
jobs, queues, and hosts.

.. toctree::
    :maxdepth: 1

    awsbatchcli/awsbsub
    awsbatchcli/awsbstat
    awsbatchcli/awsbout
    awsbatchcli/awsbkill
    awsbatchcli/awsbqueues
    awsbatchcli/awsbhosts
