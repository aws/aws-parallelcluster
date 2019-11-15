=======================================
AWS ParallelCluster - HPC for the Cloud
=======================================

|Build Status| |Version|

.. |Build Status| image:: https://travis-ci.org/aws/aws-parallelcluster.png?branch=develop
   :target: https://travis-ci.org/aws/aws-parallelcluster/
   :alt: Build Status
.. |Version| image:: https://badge.fury.io/py/aws-parallelcluster.png
    :target: https://badge.fury.io/py/aws-parallelcluster

AWS ParallelCluster is an AWS supported Open Source cluster management tool that makes it easy for you to deploy and
manage High Performance Computing (HPC) clusters in the AWS cloud.
Built on the Open Source CfnCluster project, AWS ParallelCluster enables you to quickly build an HPC compute environment in AWS.
It automatically sets up the required compute resources and a shared filesystem and offers a variety of batch schedulers such as AWS Batch, SGE, Torque, and Slurm.
AWS ParallelCluster facilitates both quick start proof of concepts (POCs) and production deployments.
You can build higher level workflows, such as a Genomics portal that automates the entire DNA sequencing workflow, on top of AWS ParallelCluster.\

Quick Start
-----------
**IMPORTANT**: you will need an **Amazon EC2 Key Pair** to be able to complete the following steps.
Please see the `Official AWS Guide <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html>`_.

First, make sure you have installed the `AWS Command Line Interface <http://>`_:

.. code-block:: sh

    $ pip install awscli

Then you can install AWS ParallelCluster:

.. code-block:: sh

    $ pip install aws-parallelcluster

Next, configure your aws credentials and default region:

.. code-block:: sh

    $ aws configure
    AWS Access Key ID [None]: YOUR_KEY
    AWS Secret Access Key [None]: YOUR_SECRET
    Default region name [us-east-1]:
    Default output format [None]:

Then, run ``pcluster configure``. A list of valid options will be displayed for each
configuration parameter. Type an option number and press ``Enter`` to select a specific option,
or just press ``Enter`` to accept the default option.

.. code-block:: ini

  $ pcluster configure
  INFO: Configuration file /dir/conf_file will be written.
  Press CTRL-C to interrupt the procedure.


  Allowed values for AWS Region ID:
  1. eu-north-1
  ...
  15. us-west-1
  16. us-west-2
  AWS Region ID [us-east-1]:
  ...

Be sure to select a region containing the EC2 key pair you wish to use. You can also import a public key using
`these instructions <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html#how-to-generate-your-own-key-and-import-it-to-aws>`_.

During the process you will be asked to set up your networking environment. The wizard will offer you the choice of
using an existing VPC or creating a new one on the fly.

.. code-block:: ini

  Automate VPC creation? (y/n) [n]:

Enter '``n``' if you already have a VPC suitable for the cluster. Otherwise you can let ``pcluster configure``
create a VPC for you. The same choice is given for the subnet: you can select a valid subnet ID for
both the master and compute nodes, or you can let ``pcluster configure`` set up everything for you.
The same choice is given for the subnet configuration: you can select a valid subnet ID for both
the master and compute nodes, or you can let pcluster configure set up everything for you.
In the latter case, just select the configuration you prefer.

.. code-block:: ini

  Automate Subnet creation? (y/n) [y]: y
  Allowed values for Network Configuration:
  1. Master in a public subnet and compute fleet in a private subnet
  2. Master and compute fleet in the same public subnet


At the end of the process a message like this one will be shown:

.. code-block:: ini

  Configuration file written to /dir/conf_file
  You can edit your configuration file or simply run 'pcluster create -c /dir/conf_file cluster-name' to create your cluster


Now you can create your first cluster:

.. code-block:: sh

  $ pcluster create myfirstcluster


After the cluster finishes creating, log in:

.. code-block:: sh

  $ pcluster ssh myfirstcluster

You can view the running compute hosts:

.. code-block:: sh

  $ qhost

For more information on any of these steps see the `Getting Started Guide`_.

.. _`Getting Started Guide`: https://docs.aws.amazon.com/parallelcluster/latest/ug/getting_started.html

Documentation
-------------

We've been working hard to greatly improve the `Documentation <https://docs.aws.amazon.com/parallelcluster/latest/ug/>`_, it's now published in 10 languages, one of the many benefits of being hosted on AWS Docs. Of most interest to new users is
the `Getting Started Guide <https://docs.aws.amazon.com/parallelcluster/latest/ug/getting_started.html>`_.

If you have changes you would like to see in the docs, please either submit feedback using the feedback link at the bottom
of each page or create an issue or pull request for the project at:
https://github.com/awsdocs/aws-parallelcluster-user-guide.

Issues
------

Please open a GitHub issue for any feedback or issues:
https://github.com/aws/aws-parallelcluster.  There is also an active AWS
HPC forum which may be helpful: https://forums.aws.amazon.com/forum.jspa?forumID=192.

Changes
-------

CfnCluster to AWS ParallelCluster
=================================
In Version `2.0.0`, we changed the name of CfnCluster to AWS ParallelCluster. With that name change we released several new features, which you can read about in the `Change Log`_.

.. _`Change Log`: https://github.com/aws/aws-parallelcluster/blob/develop/CHANGELOG.rst#200
