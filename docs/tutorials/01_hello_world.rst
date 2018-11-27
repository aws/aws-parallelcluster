.. _hello_world:

.. toctree::
   :maxdepth: 2

#############################################
Running your first job on AWS ParallelCluster
#############################################

This tutorial will walk you through running your first "Hello World" job on aws-parallelcluster.

If you haven't yet, you will need to follow the :doc:`getting started <../getting_started>` guide to install AWS
ParallelCluster and configure your CLI.

Verifying your installation
===========================

First, we'll verify that AWS ParallelCluster is correctly installed and configured. ::

        $ pcluster version

This should return the running version of AWS ParallelCluster.  If it gives you a message about configuration, you will
need to run the following to configure AWS ParallelCluster. ::

        $ pcluster configure


Creating your First Cluster
===========================

Now it's time to create our first cluster.  Because our workload isn't performance intensive, we will use the default
instance sizes of t2.micro.  For production workloads, you'll want to choose an instance size which better fits your
needs.

We're going to call our cluster "hello-world". ::

        $ pcluster create hello-world

You'll see some messages on your screen about the cluster creating.  When it's finished, it will provide the following
output::

        Starting: hello-world
        Status: parallelcluster-hello-world - CREATE_COMPLETE
        MasterPublicIP = 54.148.x.x
        ClusterUser: ec2-user
        MasterPrivateIP = 192.168.x.x
        GangliaPrivateURL = http://192.168.x.x/ganglia/
        GangliaPublicURL = http://54.148.x.x/ganglia/

The message "CREATE_COMPLETE" shows that the cluster created successfully.  It also provided us with the public and
private IP addresses of our master node.  We'll need this IP to log in.

Logging into your Master instance
=================================
You'll use your OpenSSH pem file to log into your master instance. ::

        pcluster ssh hello-world -i /path/to/keyfile.pem

Once logged in, run the command "qhost" to ensure that your compute nodes are setup and configured. ::

        [ec2-user@ip-192-168-1-86 ~]$ qhost
        HOSTNAME                ARCH         NCPU NSOC NCOR NTHR  LOAD  MEMTOT  MEMUSE  SWAPTO  SWAPUS
        ----------------------------------------------------------------------------------------------
        global                  -               -    -    -    -     -       -       -       -       -
        ip-192-168-1-125        lx-amd64        2    1    2    2  0.15    3.7G  130.8M 1024.0M     0.0
        ip-192-168-1-126        lx-amd64        2    1    2    2  0.15    3.7G  130.8M 1024.0M     0.0

As you can see, we have two compute nodes in our cluster, both with 2 threads available to them.

Running your first job using SGE
================================
Now we'll create a simple job which sleeps for a little while and then outputs it's own hostname.

Create a file called "hellojob.sh" with the following contents. ::

        #!/bin/bash
        sleep 30
        echo "Hello World from $(hostname)"

Next, submit the job using "qsub" and ensure it runs. ::

        $ qsub hellojob.sh
        Your job 1 ("hellojob.sh") has been submitted

Now, you can view your queue and check the status of the job. ::

        $ qstat
        job-ID  prior   name       user         state submit/start at     queue                          slots ja-task-ID
        -----------------------------------------------------------------------------------------------------------------
              1 0.55500 hellojob.s ec2-user     r     03/24/2015 22:23:48 all.q@ip-192-168-1-125.us-west     1

The job is currently in a running state.  Wait 30 seconds for the job to finish and run qstat again. ::

        $ qstat
        $

Now that there are no jobs in the queue, we can check for output in our current directory. ::

        $ ls -l
        total 8
        -rw-rw-r-- 1 ec2-user ec2-user 48 Mar 24 22:34 hellojob.sh
        -rw-r--r-- 1 ec2-user ec2-user  0 Mar 24 22:34 hellojob.sh.e1
        -rw-r--r-- 1 ec2-user ec2-user 34 Mar 24 22:34 hellojob.sh.o1

Here, we see our job script, an "e1" and "o1" file.  Since the e1 file is empty, there was no output to stderr.  If we
view the .o1 file, we can see any output from our job. ::

        $ cat hellojob.sh.o1
        Hello World from ip-192-168-1-125

We can see that our job successfully ran on instance "ip-192-168-1-125".

.. spelling::
   aws
   hellojob
   ip
