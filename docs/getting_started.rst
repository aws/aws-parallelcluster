.. _getting_started:

.. toctree::
   :maxdepth: 2

########################################
Getting started with AWS ParallelCluster
########################################

AWS ParallelCluster is an AWS supported Open Source cluster management tool that makes it easy for you to deploy and
manage High Performance Computing (HPC) clusters in the AWS cloud.
Built on the Open Source CfnCluster project, AWS ParallelCluster enables you to quickly build an HPC compute
environment in AWS.
It automatically sets up the required compute resources and a shared filesystem and offers a variety of batch
schedulers such as AWS Batch, SGE, Torque, and Slurm.
AWS ParallelCluster facilitates both quick start proof of concepts (POCs) and production deployments.
You can build higher level workflows, such as a Genomics portal that automates the entire DNA sequencing workflow, on
top of AWS ParallelCluster.

Installing AWS ParallelCluster
==============================

The current working version is aws-parallelcluster-|version|. The CLI is written in Python and uses BOTO for AWS
actions.
You can install the CLI with the following commands, depending on your OS.

Linux/OSX
---------
::

    $ sudo pip install aws-parallelcluster

Windows
-------
Windows support is experimental!!

Install the following packages:

* Python3.6 - https://www.python.org/download/
* pip - https://pip.pypa.io/en/stable/installing/

Once installed, you should update the Environment Variables to have the Python install directory and Python Scripts
directory in the PATH, for example: ``C:\Python36-32;C:\Python36-32\Scripts``

Now it should be possible to run the following within a command prompt window:

::

    C:\> pip install aws-parallelcluster

Upgrading
---------

To upgrade an older version of AWS ParallelCluster, you can use either of the following commands, depending on how it
was originally installed:

::

  $ sudo pip install --upgrade aws-parallelcluster

**Remember when upgrading to check that the existing config is compatible with the latest version installed.**

.. _getting_started_configuring_parallelcluster:

Configuring AWS ParallelCluster
===============================

First you'll need to setup your IAM credentials, see `AWS CLI <https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-configure.html>`_
for more information.

::

    $ aws configure
    AWS Access Key ID [None]: AKIAIOSFODNN7EXAMPLE
    AWS Secret Access Key [None]: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
    Default region name [us-east-1]: us-east-1
    Default output format [None]:

Once installed you will need to setup some initial config. The easiest way to do this is below:

::

    $ pcluster configure

This configure wizard will prompt you for everything you need to create your cluster.
You will first be prompted for your cluster template name, which is the logical name of the template you will create a
cluster from.

::

        Cluster Template [mycluster]:

Now, you will be presented with a list of valid AWS region identifiers. Choose the region in which you'd like your
cluster to run.

::

        Acceptable Values for AWS Region ID:
            us-east-1
            cn-north-1
            ap-northeast-1
            eu-west-1
            ap-southeast-1
            ap-southeast-2
            us-west-2
            us-gov-west-1
            us-gov-east-1
            us-west-1
            eu-central-1
            sa-east-1
        AWS Region ID []:

Choose a descriptive name for your VPC. Typically, this will be something like :code:`production` or :code:`test`.

::

        VPC Name [myvpc]:

Next, you will need to choose a key pair that already exists in EC2 in order to log into your master instance.
If you do not already have a key pair, refer to the EC2 documentation on `EC2 Key Pairs
<http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html>`_.

::

        Acceptable Values for Key Name:
            keypair1
            keypair-test
            production-key
        Key Name []:

Choose the VPC ID into which you'd like your cluster launched.

::

        Acceptable Values for VPC ID:
            vpc-1kd24879
            vpc-blk4982d
        VPC ID []:

Finally, choose the subnet in which you'd like your master server to run.

::

        Acceptable Values for Master Subnet ID:
            subnet-9k284a6f
            subnet-1k01g357
            subnet-b921nv04
        Master Subnet ID []:


Next, a simple cluster launches into a VPC and uses an existing subnet which supports public IP's i.e. the route table
for the subnet is :code:`0.0.0.0/0 => igw-xxxxxx`.
The VPC must have :code:`DNS Resolution = yes` and :code:`DNS Hostnames = yes`.
It should also have DHCP options with the correct :code:`domain-name` for the region, as defined in the docs: `VPC DHCP
Options <https://docs.aws.amazon.com/vpc/latest/userguide/VPC_DHCP_Options.html>`_.

Once all of those settings contain valid values, you can launch the cluster by running the create command:

::

    $ pcluster create mycluster

Once the cluster reaches the "CREATE_COMPLETE" status, you can connect using your normal SSH client/settings.
For more details on connecting to EC2 instances, check the `EC2 User Guide
<https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EC2_GetStarted.html#ec2-connect-to-instance-linux>`_.


Moving from CfnCluster to AWS ParallelCluster
=============================================

AWS ParallelCluster is an enhanced and productized version of CfnCluster.

If you are a previous CfnCluster user, we encourage you to start using and creating new clusters only with AWS
ParallelCluster.
Although you can still use CfnCluster, it will no longer be developed.

The main differences between CfnCluster and AWS ParallelCluster are listed below.

|

**AWS ParallelCluster CLI manages a different set of clusters**

Clusters created by :code:`cfncluster` CLI cannot be managed with :code:`pcluster` CLI.
The following commands will no longer work on clusters created by CfnCluster::

     pcluster list
     pcluster update cluster_name
     pcluster start cluster_name
     pcluster status cluster_name

You need to use the :code:`cfncluster` CLI to manage your old clusters.

If you need an old CfnCluster package to manage your old clusters, we recommend you install and use it
from a `Python Virtual Environment <https://docs.python.org/3/tutorial/venv.html>`_.

|

**Distinct IAM Custom Policies**

Custom IAM Policies, previously used for CfnCluster cluster creation, cannot be used with AWS ParallelCluster.
If you require custom policies you need to create the new ones by following :ref:`IAM in AWS ParallelCluster <iam>`
guide.

|

**Different configuration files**

The AWS ParallelCluster configuration file resides in the :code:`~/.parallelcluster` folder, unlike the CfnCluster one
that was created in the :code:`~/.cfncluster` folder.

You can still use your existing configuration file but this needs to be moved from :code:`~/.cfncluster/config` to
:code:`~/.parallelcluster/config`.

If you use the :code:`extra_json` configuration parameter, it must be changed as described below:

:code:`extra_json = { "cfncluster" : { } }`

has been changed to

:code:`extra_json = { "cluster" : { } }`

|

**Ganglia disabled by default**

Ganglia is disabled by default.
You can enable it by setting the :code:`extra_json` parameter as described below:

:code:`extra_json = { "cluster" : { "ganglia_enabled" : "yes" } }`

and changing the Master SG to allow connections to port 80.
The :code:`parallelcluster-<CLUSTER_NAME>-MasterSecurityGroup-<xxx>` Security Group has to be modified by
`adding a new Security Group Rule
<https://docs.aws.amazon.com/en_us/AWSEC2/latest/UserGuide/using-network-security.html#adding-security-group-rule>`_
to allow Inbound connection to the port 80 from your Public IP.

.. spelling::
   aws
   wJalrXUtnFEMI
   MDENG
   bPxRfiCYEXAMPLEKEY
