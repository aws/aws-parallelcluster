==============================
CfnCluster - HPC for the Cloud
==============================

|Build Status| |Version|

.. |Build Status| image:: https://travis-ci.org/awslabs/cfncluster.png?branch=develop
   :target: https://travis-ci.org/awslabs/cfncluster/
   :alt: Build Status
.. |Version| image:: https://badge.fury.io/py/cfncluster.png
    :target: https://badge.fury.io/py/cfncluster

CfnCluster ("cloud formation cluster") is a framework that deploys and
maintains high performance computing clusters on Amazon Web Services
(AWS). Developed by AWS, CfnCluster facilitates both quick start proof
of concepts (POCs) and production deployments. CfnCluster supports
many different types of clustered applications and can easily be
extended to support different frameworks. The CLI is stateless,
everything is done using CloudFormation or resources within AWS.\

Quick Start
-----------
First, install the library:

.. code-block:: sh

    $ pip install cfncluster

Next, configure your aws credentials and default region:

.. code-block:: sh

    $ aws configure
    AWS Access Key ID [None]: YOUR_KEY
    AWS Secret Access Key [None]: YOUR_SECRET
    Default region name [us-east-1]:
    Default output format [None]:

Then, run cfncluster configure:

.. code-block:: ini

  $ cfncluster configure
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

Now you can create your first cluster;

.. code-block:: sh

  $ cfncluster create myfirstcluster


After the cluster finishes creating, log in:

.. code-block:: sh

  $ cfncluster ssh myfirstcluster

You can view the running compute hosts:

.. code-block:: sh

  $ qhost

For more information on any of these steps see the `Getting Started Guide`_.

.. _`Getting Started Guide`: https://cfncluster.readthedocs.io/en/latest/getting_started.html

Documentation
-------------

Documentation is part of the project and is published to -
https://cfncluster.readthedocs.io/. Of most interest to new users is
the Getting Started Guide -
https://cfncluster.readthedocs.io/en/latest/getting_started.html.

Issues
------

Please open a GitHub issue for any feedback or issues:
https://github.com/awslabs/cfncluster.  There is also an active AWS
HPC forum which may be helpful:https://forums.aws.amazon.com/forum.jspa?forumID=192.

Changes
-------

CfnCluster 1.6 IAM Change
=========================
Between CfnCluster 1.5.3 and 1.6.0 we made a change to the CfnClusterInstancePolicy that adds “s3:GetObject” permissions
on objects in <REGION>-cfncluster bucket, "autoscaling:SetDesiredCapacity", "autoscaling:DescribeTags" permissions and
"cloudformation:DescribeStacks" permissions on <REGION>:<ACCOUNT_NAME>:<STACK_NAME>.

If you’re using a custom policy (e.g. you specify "ec2_iam_role" in your config) be sure it includes this new permission. See https://cfncluster.readthedocs.io/en/latest/iam.html

CfnCluster 1.5 IAM Change
=========================
Between CfnCluster 1.4.2 and 1.5.0 we made a change to the CfnClusterInstancePolicy that adds “ec2:DescribeVolumes” permissions. If you’re using a custom policy (e.g. you specify "ec2_iam_role" in your config) be sure it includes this new permission. See https://cfncluster.readthedocs.io/en/latest/iam.html

CfnCluster 1.2 and Earlier
==========================

For various security (on our side) and maintenance reasons, CfnCluster
1.2 and earlier have been deprecated.  AWS-side resources necessary to
create a cluster with CfnCluster 1.2 or earlier are no longer
available.  Existing clusters will continue to operate, but new
clusters can not be created.
