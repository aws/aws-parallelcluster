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
manage High Performance Computing (HPC) clusters in the AWS cloud. Built on the Open Source CfnCluster project,
AWS ParallelCluster enables you to quickly build an HPC compute environment in AWS.  It automatically sets up the
required compute resources and a shared filesystem and offers a variety of batch schedulers such as AWS Batch, SGE,
Torque, and Slurm.  AWS ParallelCluster facilitates both quick start proof of concepts (POCs) and production
deployments.  You can build higher level workflows, such as a Genomics portal that automates the entire DNA sequencing
workflow, on top of AWS ParallelCluster.

-----------
Quick Start
-----------

Install the library using pip:

.. code-block:: sh

    $ pip install aws-parallelcluster

Configure your AWS credentials and default region:

.. code-block:: sh

    $ aws configure
    AWS Access Key ID [None]: YOUR_KEY
    AWS Secret Access Key [None]: YOUR_SECRET
    Default region name [us-east-1]:
    Default output format [None]:

Initialize the pcluster environment:

.. code-block:: ini

  $ pcluster configure
  Cluster Template [default]:
  AWS Access Key ID []:
  AWS Secret Access Key ID []:
  Acceptable Values for AWS Region ID:
      ap-south-1
      ...
      us-west-2
  AWS Region ID [us-east-1]:
  VPC Name [myvpc]:
  Acceptable Values for Key Name:
    keypair1
    keypair-test
    production-key
  Key Name []:
  Acceptable Values for VPC ID:
    vpc-1kd24879
    vpc-blk4982d
  VPC ID []:
  Acceptable Values for Master Subnet ID:
    subnet-9k284a6f
    subnet-1k01g357
    subnet-b921nv04
  Master Subnet ID []:

Now create your first cluster stack:

.. code-block:: sh

  $ pcluster create myfirstcluster

After the cluster creation process finishes, login to the head node:

.. code-block:: sh

  $ pcluster ssh myfirstcluster

View the running compute hosts based on the selected scheduler:

.. code-block:: sh

  $ qhost                              [ Grid Engine ]
  $ pbsnodes -a                        [ Torque ]
  $ sinfo -N                           [ Slurm ]
  $ awsbhosts -c myfirstcluster -d     [ AWS Batch ]

For more information on any of these steps, please refer to the `Getting Started Guide`_.

.. _`Getting Started Guide`: https://aws-parallelcluster.readthedocs.io/en/latest/getting_started.html

-------------
Documentation
-------------

Documentation for AWS ParallelCluster can be found by visiting the project page:
https://aws-parallelcluster.readthedocs.io/

New users are strongly encouraged to review the Getting Started Guide:
https://aws-parallelcluster.readthedocs.io/en/latest/getting_started.html

------
Issues
------

Please visit the AWS ParallelCluster Github project site to provide feedback, request new features, or report bugs:
https://github.com/aws/aws-parallelcluster.

The AWS HPC Forum is monitored by the ParallelCluster development team and may also be helpful:
https://forums.aws.amazon.com/forum.jspa?forumID=192.

-------
Changes
-------

CfnCluster 1.6 IAM Change
=========================
Between CfnCluster 1.5.4 and 1.6.0, we made a change to the CfnClusterInstancePolicy that adds "s3:GetObject" permissions
on objects in <REGION>-cfncluster bucket, "autoscaling:SetDesiredCapacity", "autoscaling:DescribeTags" permissions, and
"cloudformation:DescribeStacks" permissions on <REGION>:<ACCOUNT_ID>:stack/cfncluster-*.

If you are using a custom policy (e.g. "ec2_iam_role" is specified in your config), please be sure it includes this new permission.
For more detailed information, please visit: https://aws-parallelcluster.readthedocs.io/en/latest/iam.html

CfnCluster 1.5 IAM Change
=========================
Between CfnCluster 1.4.2 and 1.5.0, we made a change to the CfnClusterInstancePolicy that adds "ec2:DescribeVolumes" permissions. If you are using a custom policy (e.g. "ec2_iam_role" is specified in your config), please be sure it includes this new permission.
For more detailed information, please visit: https://aws-parallelcluster.readthedocs.io/en/latest/iam.html

CfnCluster 1.2 and Earlier
==========================
For various maintenance and security reasons (on our side), CfnCluster 1.2 and earlier have been deprecated.  AWS-side resources necessary to create a cluster with CfnCluster 1.2 or earlier are no longer available.  Existing clusters will continue to operate, but new clusters cannot be created.
