.. _tutorials_batch_mpi:

.. toctree::
   :maxdepth: 2

##############################################################
Running an MPI job with ParallelCluster and awsbatch scheduler
##############################################################

This tutorial will walk you through running a simple MPI job with ``awsbatch`` as a scheduler.

If you haven't yet, you will need to follow the :doc:`getting started<../getting_started>` guide to install AWS
ParallelCluster and configure your CLI.
Also, make sure to read through the :ref:`awsbatch networking setup<awsbatch_networking>` documentation before
moving to the next step.

Creating the cluster
====================

As first step let's create a simple configuration for a cluster that uses ``awsbatch`` as scheduler.
Make sure to replace the missing data in the ``vpc`` section and the ``key_name`` field with the resources you created
at configuration time.

.. literalinclude:: code_samples/batch_mpi/cluster_config.ini
   :language: INI


You can now start the creation of the cluster. We're going to call our cluster "awsbatch-tutorial".::

    $ pcluster create -c /path/to/the/created/config/aws_batch.config -t awsbatch awsbatch-tutorial

You'll see some messages on your screen about the cluster creating.  When it's finished, it will provide the following
output::

    Beginning cluster creation for cluster: awsbatch-tutorial
    Creating stack named: parallelcluster-awsbatch-tutorial
    Status: parallelcluster-awsbatch-tutorial - CREATE_COMPLETE
    MasterPublicIP: 54.160.xxx.xxx
    ClusterUser: ec2-user
    MasterPrivateIP: 10.0.0.15


Logging into your Master instance
=================================
Although the :doc:`AWS ParallelCluster Batch CLI<../awsbatchcli>` commands are all available on the client machine
where ParallelCluster is installed, we are going to ssh into the Master node and submit the jobs from there, so that
we can take advantage of the NFS volume that is shared between the Master and all Docker instances that run Batch jobs.

You'll use your SSH pem file to log into your master instance ::

    $ pcluster ssh awsbatch-tutorial -i /path/to/keyfile.pem

Once logged in, run the commands ``awsbqueues`` and ``awsbhosts`` to show the configured AWS Batch queue
and the running ECS instances. ::

    [ec2-user@ip-10-0-0-111 ~]$ awsbqueues
    jobQueueName                       status
    ---------------------------------  --------
    parallelcluster-awsbatch-tutorial  VALID

    [ec2-user@ip-10-0-0-111 ~]$ awsbhosts
    ec2InstanceId        instanceType    privateIpAddress    publicIpAddress      runningJobs
    -------------------  --------------  ------------------  -----------------  -------------
    i-0d6a0c8c560cd5bed  m4.large        10.0.0.235          34.239.174.236                 0

As you can see, we have one single running host. This is due to the value we chose for min_vcpus in the config.
If you want to display additional details about the AWS Batch queue and hosts you can simply add the ``-d`` flag
to the command.

Running your first job using AWS Batch
======================================
Before moving to MPI let's create a simple dummy jobs which sleeps for a little while and then outputs it's own
hostname, greeting the name passed as parameter.

Create a file called "hellojob.sh" with the following content.

.. literalinclude:: code_samples/batch_mpi/batch_hello_world.sh
   :language: bash

Next, submit the job using ``awsbsub`` and ensure it runs. ::

        $ awsbsub -jn hello -cf hellojob.sh Luca
        Job 6efe6c7c-4943-4c1a-baf5-edbfeccab5d2 (hello) has been submitted.

Now, you can view your queue and check the status of the job. ::

        $ awsbstat
        jobId                                 jobName      status    startedAt            stoppedAt    exitCode
        ------------------------------------  -----------  --------  -------------------  -----------  ----------
        6efe6c7c-4943-4c1a-baf5-edbfeccab5d2  hello        RUNNING   2018-11-12 09:41:29  -            -

You can even see the detailed information for the job. ::

        $ awsbstat 6efe6c7c-4943-4c1a-baf5-edbfeccab5d2
        jobId                    : 6efe6c7c-4943-4c1a-baf5-edbfeccab5d2
        jobName                  : hello
        createdAt                : 2018-11-12 09:41:21
        startedAt                : 2018-11-12 09:41:29
        stoppedAt                : -
        status                   : RUNNING
        statusReason             : -
        jobDefinition            : parallelcluster-myBatch:1
        jobQueue                 : parallelcluster-myBatch
        command                  : /bin/bash -c 'aws s3 --region us-east-1 cp s3://parallelcluster-mybatch-lui1ftboklhpns95/batch/job-hellojob_sh-1542015680924.sh /tmp/batch/job-hellojob_sh-1542015680924.sh; bash /tmp/batch/job-hellojob_sh-1542015680924.sh Luca'
        exitCode                 : -
        reason                   : -
        vcpus                    : 1
        memory[MB]               : 128
        nodes                    : 1
        logStream                : parallelcluster-myBatch/default/c75dac4a-5aca-4238-a4dd-078037453554
        log                      : https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#logEventViewer:group=/aws/batch/job;stream=parallelcluster-myBatch/default/c75dac4a-5aca-4238-a4dd-078037453554
        -------------------------

The job is currently in a RUNNING state. Wait 30 seconds for the job to finish and run ``awsbstat`` again. ::

        $ awsbstat
        jobId                                 jobName      status    startedAt            stoppedAt    exitCode
        ------------------------------------  -----------  --------  -------------------  -----------  ----------

You can see that the job is in the SUCCEEDED status. ::

        $ awsbstat -s SUCCEEDED
        jobId                                 jobName      status     startedAt            stoppedAt              exitCode
        ------------------------------------  -----------  ---------  -------------------  -------------------  ----------
        6efe6c7c-4943-4c1a-baf5-edbfeccab5d2  hello        SUCCEEDED  2018-11-12 09:41:29  2018-11-12 09:42:00           0

Now that there are no jobs in the queue, we can check for output through the ``awsbout`` command. ::

        $ awsbout 6efe6c7c-4943-4c1a-baf5-edbfeccab5d2
        2018-11-12 09:41:29: Starting Job 6efe6c7c-4943-4c1a-baf5-edbfeccab5d2
        download: s3://parallelcluster-mybatch-lui1ftboklhpns95/batch/job-hellojob_sh-1542015680924.sh to tmp/batch/job-hellojob_sh-1542015680924.sh
        2018-11-12 09:42:00: Hello Luca from ip-172-31-4-234

We can see that our job successfully ran on instance "ip-172-31-4-234".

Also if you look into the ``/shared`` directory you will find a secret message for you :)

Feel free to take a look at the :doc:`AWS ParallelCluster Batch CLI documentation<../awsbatchcli>` in order to
explore all the available features that are not part of this demo (How about running an array job?).
Once you are ready let's move on and see how to submit an MPI job!

Running an MPI job in a multi-node parallel environment
=======================================================
In this section you'll learn how to submit a simple MPI job which gets executed in a AWS Batch multi-node parallel
environment.

First of all, while still logged into the Master node, let's create a file in the
``/shared`` directory, named ``mpi_hello_world.c``, that contains the following MPI program:

.. literalinclude:: code_samples/batch_mpi/mpi_hello_world.c
   :language: c

Now save the following code as ``submit_mpi.sh``:

.. literalinclude:: code_samples/batch_mpi/submit_mpi.sh
   :language: bash

And that's all. We are now ready to submit our first MPI job and make it run concurrently on 3 nodes::

    $ awsbsub -n 3 -cf submit_mpi.sh

Let's now monitor the job status and wait for it to enter the ``RUNNING`` status::

    $ watch awsbstat -d

Once the job enters the ``RUNNING`` status we can look at its output. Simply append ``#0`` to the job id in order to
show the output of the main node, while use #1 and #2 to display the output of the compute nodes::

    [ec2-user@ip-10-0-0-111 ~]$ awsbout -s 5b4d50f8-1060-4ebf-ba2d-1ae868bbd92d#0
    2018-11-27 15:50:10: Job id: 5b4d50f8-1060-4ebf-ba2d-1ae868bbd92d#0
    2018-11-27 15:50:10: Initializing the environment...
    2018-11-27 15:50:10: Starting ssh agents...
    2018-11-27 15:50:11: Agent pid 7
    2018-11-27 15:50:11: Identity added: /root/.ssh/id_rsa (/root/.ssh/id_rsa)
    2018-11-27 15:50:11: Mounting shared file system...
    2018-11-27 15:50:11: Generating hostfile...
    2018-11-27 15:50:11: Detected 1/3 compute nodes. Waiting for all compute nodes to start.
    2018-11-27 15:50:26: Detected 1/3 compute nodes. Waiting for all compute nodes to start.
    2018-11-27 15:50:41: Detected 1/3 compute nodes. Waiting for all compute nodes to start.
    2018-11-27 15:50:56: Detected 3/3 compute nodes. Waiting for all compute nodes to start.
    2018-11-27 15:51:11: Starting the job...
    download: s3://parallelcluster-awsbatch-tutorial-iwyl4458saiwgwvg/batch/job-submit_mpi_sh-1543333713772.sh to tmp/batch/job-submit_mpi_sh-1543333713772.sh
    2018-11-27 15:51:12: ip container: 10.0.0.180
    2018-11-27 15:51:12: ip host: 10.0.0.245
    2018-11-27 15:51:12: Compiling...
    2018-11-27 15:51:12: Running...
    2018-11-27 15:51:12: Hello I'm the main node! I run the mpi job!
    2018-11-27 15:51:12: Warning: Permanently added '10.0.0.199' (RSA) to the list of known hosts.
    2018-11-27 15:51:12: Warning: Permanently added '10.0.0.147' (RSA) to the list of known hosts.
    2018-11-27 15:51:13: Hello world from processor ip-10-0-0-180.ec2.internal, rank 1 out of 6 processors
    2018-11-27 15:51:13: Hello world from processor ip-10-0-0-199.ec2.internal, rank 5 out of 6 processors
    2018-11-27 15:51:13: Hello world from processor ip-10-0-0-180.ec2.internal, rank 0 out of 6 processors
    2018-11-27 15:51:13: Hello world from processor ip-10-0-0-199.ec2.internal, rank 4 out of 6 processors
    2018-11-27 15:51:13: Hello world from processor ip-10-0-0-147.ec2.internal, rank 2 out of 6 processors
    2018-11-27 15:51:13: Hello world from processor ip-10-0-0-147.ec2.internal, rank 3 out of 6 processors

    [ec2-user@ip-10-0-0-111 ~]$ awsbout -s 5b4d50f8-1060-4ebf-ba2d-1ae868bbd92d#1
    2018-11-27 15:50:52: Job id: 5b4d50f8-1060-4ebf-ba2d-1ae868bbd92d#1
    2018-11-27 15:50:52: Initializing the environment...
    2018-11-27 15:50:52: Starting ssh agents...
    2018-11-27 15:50:52: Agent pid 7
    2018-11-27 15:50:52: Identity added: /root/.ssh/id_rsa (/root/.ssh/id_rsa)
    2018-11-27 15:50:52: Mounting shared file system...
    2018-11-27 15:50:52: Generating hostfile...
    2018-11-27 15:50:52: Starting the job...
    download: s3://parallelcluster-awsbatch-tutorial-iwyl4458saiwgwvg/batch/job-submit_mpi_sh-1543333713772.sh to tmp/batch/job-submit_mpi_sh-1543333713772.sh
    2018-11-27 15:50:53: ip container: 10.0.0.199
    2018-11-27 15:50:53: ip host: 10.0.0.227
    2018-11-27 15:50:53: Compiling...
    2018-11-27 15:50:53: Running...
    2018-11-27 15:50:53: Hello I'm a compute note! I let the main node orchestrate the mpi execution!

We can now confirm that the job completed successfully::

    [ec2-user@ip-10-0-0-111 ~]$ awsbstat -s ALL
    jobId                                 jobName        status     startedAt            stoppedAt            exitCode
    ------------------------------------  -------------  ---------  -------------------  -------------------  ----------
    5b4d50f8-1060-4ebf-ba2d-1ae868bbd92d  submit_mpi_sh  SUCCEEDED  2018-11-27 15:50:10  2018-11-27 15:51:26  -

In case you want to terminate a job before it ends you can use the ``awsbkill`` command.

.. spelling::
   aws
   awsbatch
   hellojob
   ip
   vcpus
