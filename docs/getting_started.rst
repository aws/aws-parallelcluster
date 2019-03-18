.. _getting_started:

.. toctree::
   :maxdepth: 2

########################################
Getting started with AWS ParallelCluster
########################################

AWS ParallelCluster is an AWS-supported Open Source cluster management tool that makes it easy to deploy and
manage High Performance Computing (HPC) clusters in the AWS cloud.

AWS ParallelCluster supports the following features:

- Multiple Linux flavors including Amazon Linux, CentOS, and Ubuntu.
- Configurable autoscaling of compute resources.
- Custom AMIs.
- Shared file systems built from EBS, EFS, and FSxL (Lustre) volumes.
- EBS RAID functionality.
- Private subnet deployments.
- Multiple HPC schedulers including AWS Batch, Grid Engine, Torque, and Slurm.

AWS ParallelCluster facilitates both quick start proof-of-concepts (POCs) and massive production deployments.
It can be used to orchestrate higher level workflow use cases such as automated DNA sequencing pipelines, 
global weather forecasting, cryptography, fluid dynamics simulations, jet engine design, credit card fraud
detection, insurance risk modeling, and protein-ligand docking analysis.

Installing AWS ParallelCluster
==============================

The current working version is aws-parallelcluster-|version|. The CLI is written in Python and uses the Boto library
to perform AWS actions.
The CLI can be installed with the following commands:

Linux/OSX
---------
::

    $ sudo pip install aws-parallelcluster

Windows
-------
NOTE - Windows support is experimental!!

Install the following packages:

* Python3.6 - https://www.python.org/download/
* pip - https://pip.pypa.io/en/stable/installing/

Once installed, update the Environment Variables to have the Python install directory and Python Scripts
directory in the PATH, for example: ``C:\Python36-32;C:\Python36-32\Scripts``

It should now be possible to run the following within a command prompt window:

::

    C:\> pip install aws-parallelcluster

Upgrading
---------

To upgrade an older version of AWS ParallelCluster:

::

  $ sudo pip install --upgrade aws-parallelcluster

**Please remember to check that the existing configuration is compatible with the version of ParallelCluster being installed.**

.. _getting_started_configuring_parallelcluster:

Configuring AWS ParallelCluster
===============================

Once installed, you will need to perform some initial configuration steps.  The easiest way to do this is:

::

    $ pcluster configure

The pcluster configure wizard will prompt for all information required to create your cluster.

You must first provide the name of the cluster template:

::

        Cluster Template [mycluster]:

You will then be prompted to provide AWS Access and Secret Keys.  Enter the keys for an IAM user with administrative
privileges.  These can also be read from your environment variables or the AWS CLI config:

::

        AWS Access Key ID []:
        AWS Secret Access Key ID []:

A list of valid AWS region identifiers will then be provided.  Choose the region that the cluster will deployed into:

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

Choose a descriptive name for your VPC.  Typically, this will be something like :code:`production`, :code:`test`, or :code:`dev`.

::

        VPC Name [myvpc]:

Now choose a key pair that already exists in EC2 in order to log into your master instance.
If you do not already have a key pair, please refer to the EC2 documentation on `EC2 Key Pairs
<http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html>`_ for additional guidance.

::

        Acceptable Values for Key Name:
            keypair1
            keypair-test
            production-key
        Key Name []:

Choose the VPC ID that the cluster will be launched from:

::

        Acceptable Values for VPC ID:
            vpc-1kd24879
            vpc-blk4982d
        VPC ID []:

Choose the subnet into which the master server will be created:

::

        Acceptable Values for Master Subnet ID:
            subnet-9k284a6f
            subnet-1k01g357
            subnet-b921nv04
        Master Subnet ID []:


The cluster will launch from a VPC and use an existing subnet which supports public IP's i.e. the route table
for the subnet is :code:`0.0.0.0/0 => igw-xxxxxx`.
The VPC must have :code:`DNS Resolution = yes` and :code:`DNS Hostnames = yes`.
It should also have DHCP options with the correct :code:`domain-name` for the region, as defined in the documentation: `VPC DHCP
Options <http://docs.aws.amazon.com/AmazonVPC/latest/UserGuide/VPC_DHCP_Options.html>`_.

Once all of these settings contain valid values, the cluster can be launched by running the create command:

::

    $ pcluster create mycluster

Once the cluster reaches the "CREATE_COMPLETE" status, connect using your normal SSH client/settings.
For more details on connecting to EC2 instances, check the `EC2 User Guide
<https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EC2_GetStarted.html#ec2-connect-to-instance-linux>`_.


Moving from CfnCluster to AWS ParallelCluster
=============================================

AWS ParallelCluster is an enhanced and productized version of CfnCluster.

If you are a previous CfnCluster user, we encourage you to start using and creating new clusters using only
AWS ParallelCluster.
Although you can still use CfnCluster, it will no longer be developed.

The primary differences between CfnCluster and AWS ParallelCluster are described below.

|

**AWS ParallelCluster CLI manages a different set of clusters**

Clusters created by :code:`cfncluster` CLI cannot be managed with :code:`pcluster` CLI.
The following commands will no longer work on clusters created by CfnCluster::

     pcluster list
     pcluster update cluster_name
     pcluster start cluster_name
     pcluster status cluster_name

You must use the :code:`cfncluster` CLI to manage your old clusters.

If an old CfnCluster package is still required to manage your legacy clusters, we recommend installing and using
CfnCluster from a `Python Virtual Environment <https://docs.python.org/3/tutorial/venv.html>`_.

|

**Distinct IAM Custom Policies**

Custom IAM Policies cannot be used with AWS ParallelCluster.
If your environment requires custom IAM policies, you must create the new ones by following the :ref:`IAM in AWS ParallelCluster <iam>`
guide.

|

**Different configuration files**

The AWS ParallelCluster configuration file resides in the :code:`~/.parallelcluster` folder, unlike the CfnCluster one,
which was created in the :code:`~/.cfncluster` folder.

You can still use your existing configuration file by moving or copying from :code:`~/.cfncluster/config` to
:code:`~/.parallelcluster/config`.

The :code:`extra_json` configuration parameter must be changed as described below:

:code:`extra_json = { "cfncluster" : { } }`

has been changed to

:code:`extra_json = { "cluster" : { } }`

|

**Ganglia disabled by default**

Ganglia is disabled by default in ParallelCluster.
You can enable it by setting the :code:`extra_json` parameter as described below:

:code:`extra_json = { "cluster" : { "ganglia_enabled" : "yes" } }`

The :code:`parallelcluster-<CLUSTER_NAME>-MasterSecurityGroup-<xxx>` Security Group must also be modified by
`adding a new Security Group Rule
<https://docs.aws.amazon.com/en_us/AWSEC2/latest/UserGuide/using-network-security.html#adding-security-group-rule>`_
to allow Inbound connection to port 80 from the "public" IP block that needs to access Ganglia.

.. spelling::
   aws
