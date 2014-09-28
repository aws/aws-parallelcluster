cfncluster
==========

cfncluster is a framework that deploys and maintains HPC clusters on 
AWS. It is reasonably agnostic to what the cluster is for and can easily be 
extended to support different frameworks. The CLI is stateless, 
everything is done using CloudFormation or resources within AWS.

### Installation

The current working version is cfncluster-0.0.12. The CLI is written in python and uses BOTO for AWS actions. You can install the CLI with the following command:

#### Linux/OSX

```
$ sudo pip install cfncluster
```
or
```
$ sudo easy_install cfncluster
```

#### Windows
Windows support is experimental!!

Install the following packages:

Python2.7 - https://www.python.org/download/

setuptools - https://pypi.python.org/pypi/setuptools#windows-7-or-graphical-install

Once installed, you should update the Environment Variables to have the Python install directory and Python Scripts directory in the PATH, for example: C:\Python27;C:\Python27\Scripts

Now it should be possible to run the following within a command prompt window:

```
C:\> easy_install cfncluster
```

#### Upgrading

To upgrade an older version of cfncluster, you can use either of the following commands, depening on how it was originally installed:

```
$ sudo pip install --upgrade cfncluster
```
or
```
$ sudo easy_install -U cfncluster
```

** Remember when upgrading to check that the exiting config is compatible with the latest version installed.

### Configuration

Once installed you will need to setup some initial config. The easiest way to do this is below:

```
$ cfncluster create mycluster
Starting: mycluster
Default config /home/ec2-user/.cfncluster/config not found
You can copy a template from here: /usr/lib/python2.6/site-packages/cfncluster/examples/config
$
$ mkdir ~/.cfncluster
$ cp /usr/lib/python2.6/site-packages/cfncluster/examples/config ~/.cfncluster
```

You should now edit the config and set some defaults before launching the cluster. First define a keypair that already exists in EC2. If you do not already have a keypair, refer to the EC2 documentation on EC2 Key Pairs - http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html

```
[keypair mykey]
key_location = /path/to/key.pem
````

Then you should associate that keypair with the cluster template.
````
[cluster default]
# Name of an existing EC2 KeyPair to enable SSH access to the instances.
key_name = mykey
```

Next, a simple cluster launches into a VPC and uses an existing subnet which supports public IP's i.e. the route table for the subnet is 0.0.0.0/0 => igw-xxxxxx. The VPC must have "DNS Resolution = yes" and "DNS Hostnames = yes". It should also have DHCP options with the correct "domain-name" for the region, as defined in the docs: http://docs.aws.amazon.com/AmazonVPC/latest/UserGuide/VPC_DHCP_Options.html

```
## VPC Settings
[vpc public]
# ID of the VPC you want to provision cluster into.
vpc_id = CHANGE ME, for example vpc-a1b2c3d4
# ID of the Subnet you want to provision the Master server into
master_subnet_id = CHANGE ME, for exaple subnet-1ab2c3d4
```

Once all of those settings contain valid values, you can launch the cluster by repeating the command that was used at the start.
```
$ cfncluster create mycluster
```
Once the cluster reaches the "CREATE_COMPLETE" status, you can connect using your normal SSH client/settings. For more details on connecting to EC2 instances, check the EC2 User Guide - http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-connect-to-instance-linux.html#using-ssh-client
