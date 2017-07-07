.. _getting_started:

.. toctree::
   :maxdepth: 2

###############################
Getting started with CfnCluster
###############################

CfnCluster ("cloud formation cluster") is a framework that deploys and maintains high performance computing clusters on Amazon Web Services (AWS). Developed by AWS, CfnCluster facilitates both quick start proof of concepts (POCs) and production deployments. CfnCluster supports many different types of clustered applications and can easily be extended to support different frameworks. Download CfnCluster today to see how CfnCluster's command line interface leverages AWS CloudFormation templates and other AWS cloud services.

Installing CfnCluster
=====================

The current working version is CfnCluster-|version|. The CLI is written in Python and uses BOTO for AWS actions. You can install the CLI with the following commands, depending on your OS.

Linux/OSX
---------
::

	$ sudo pip install cfncluster

or::

	$ sudo easy_install cfncluster

Windows
-------
Windows support is experimental!!

Install the following packages:

* Python2.7 - https://www.python.org/download/
* setuptools - https://pypi.python.org/pypi/setuptools#windows-7-or-graphical-install

Once installed, you should update the Environment Variables to have the Python install directory and Python Scripts directory in the PATH, for example: ``C:\Python27;C:\Python27\Scripts``

Now it should be possible to run the following within a command prompt window:

::

	C:\> easy_install CfnCluster

Upgrading
---------

To upgrade an older version of CfnCluster, you can use either of the following commands, depening on how it was originally installed:

::

  $ sudo pip install --upgrade cfncluster

or

::

	$ sudo easy_install -U cfncluster

**Remember when upgrading to check that the exiting config is compatible with the latest version installed.**

Configuring CfnCluster
======================

Once installed you will need to setup some initial config. The easiest way to do this is below:

::

	$ cfncluster configure

This configure wizard will prompt you for everything you need to create your cluster.  You will first be prompted for your cluster template name, which is the logical name of the template you will create a cluster from.

::

        Cluster Template [mycluster]:

Next, you will be prompted for your AWS Access & Secret Keys.  Enter the keys for an IAM user with administrative privledges.  These can also be read from your environment variables or the  aws CLI config.

::

        AWS Access Key ID []:
        AWS Secret Access Key ID []:

Now, you will be presented with a list of valid AWS region identifiers.  Choose the region in which you'd like your cluster to run.

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
            us-west-1
            eu-central-1
            sa-east-1
        AWS Region ID []:

Choose a descriptive name for your VPC. Typically, this will something like :code:`production` or :code:`test`.

::

        VPC Name [myvpc]:

Next, you will need to choose a keypair that already exists in EC2 in order to log into your master instance.  If you do not already have a keypair, refer to the EC2 documentation on `EC2 Key Pairs <http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html>`_.

::

        Acceptable Values for Key Name:
            keypair1
            keypair-test
            production-key
        Key Name []:

Choose the VPC ID in which you'd like your cluster launched into.

::

        Acceptable Values for VPC ID:
            vpc-1kd24879
            vpc-blk4982d
        VPC ID []:

Finally, choose the subnet in which you'd like your master server to run in.

::

        Acceptable Values for Master Subnet ID:
            subnet-9k284a6f
            subnet-1k01g357
            subnet-b921nv04
        Master Subnet ID []:


Next, a simple cluster launches into a VPC and uses an existing subnet which supports public IP's i.e. the route table for the subnet is :code:`0.0.0.0/0 => igw-xxxxxx`. The VPC must have :code:`DNS Resolution = yes` and :code:`DNS Hostnames = yes`. It should also have DHCP options with the correct :code:`domain-name` for the region, as defined in the docs: `VPC DHCP Options <http://docs.aws.amazon.com/AmazonVPC/latest/UserGuide/VPC_DHCP_Options.html>`_.

Once all of those settings contain valid values, you can launch the cluster by running the create command:

::

	$ cfncluster create mycluster

Once the cluster reaches the "CREATE_COMPLETE" status, you can connect using your normal SSH client/settings. For more details on connecting to EC2 instances, check the `EC2 User Guide <http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-connect-to-instance-linux.html#using-ssh-client>`_.
