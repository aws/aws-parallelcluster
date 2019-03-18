.. _processes:

AWS ParallelCluster Processes
=============================

This section applies only to HPC clusters deployed with one of the supported traditional job schedulers
(Grid Engine, Slurm or Torque).
In these cases, AWS ParallelCluster manages the compute node provisioning and removal
by interacting with both the Auto Scaling Group (ASG) and the underlying job scheduler.

For HPC clusters based on AWS Batch, ParallelCluster instead relies on the capabilities provided by the AWS Batch
for management of the compute nodes.

.. toctree::

General Overview
----------------
The life cycle of a cluster begins after it is created by a user.
Typically, this is done from the Command Line Interface (CLI).
Once created, a cluster will exist until it is deleted.
The AWS ParallelCluster daemons run on the cluster nodes and are mainly aimed at managing elasticity.
The diagram below represents a typical user workflow and cluster life cycle, while the next sections
describe the AWS ParallelCluster daemons used to manage the cluster:

.. image:: images/workflow.svg
    :align: center
    :width: 65%

jobwatcher
----------
jobwatcher is a root-owned process that monitors the configured scheduler (Grid Engine, Torque, or Slurm).
Once per minute, it will evaluate the queue to determine if scaling up is necessary.

.. image:: images/jobwatcher.svg
    :align: center
    :width: 20%

sqswatcher
----------
sqswatcher monitors SQS messages emitted by Auto Scaling when state changes occur within the cluster.
When an new instance comes online, an "instance ready" message is submitted to SQS which is picked up by
sqswatcher running on the master server.  These messages are used to notify the queue manager when new instances come
online or are terminated, so they can be added or removed from the queue accordingly.

.. image:: images/sqswatcher.svg
    :align: center
    :width: 45%

nodewatcher
-----------
nodewatcher runs on each node in the compute fleet.  After the user defined ``scaledown_idletime`` period, the instance is terminated.

.. image:: images/nodewatcher.svg
    :align: center
    :width: 35%

.. spelling::
    sqs
