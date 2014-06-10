cfncluster
==========

cfncluster is a sample code framework that deploys and maintains clusters on 
AWS. It is reasonably agnostic to what the cluster is for and can easily be 
extended to support different frameworks. The the CLI is stateless, 
everything is done using CloudFormation or resources within AWS.

### Installation

The current working version is cfncluster-0.0.5. The CLI is written in python and uses BOTO for AWS actions. You can install the CLI with the following command:

#### Linux/OSX

```
$ sudo easy_install cfncluster
```
or
```
$ sudo pip install cfncluster
```

#### Windows
Windows support is experimental!!

Install the following packages:

Python2.7 - https://www.python.org/download/
pyCrypto - http://www.voidspace.org.uk/python/modules.shtml#pycrypto
setuptools - https://pypi.python.org/pypi/setuptools#windows-7-or-graphical-install

Once installed, you should update the Environment Variables to have the Python install directory and Python Scripts directory in the PATH, for example: C:\Python27;C:\Python27\Scripts

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

You should now edit the config and set some defaults before launching the cluster. First define a keypair that already exists in EC2.

```
[keypair mykey]
key_location = /path/to/key.pem
Then you should associate that keypair with the cluster template.
[cluster default]
# Name of an existing EC2 KeyPair to enable SSH access to the instances.
key_name = mykey
```

Finally, a base cluster launches into a VPC and uses an existing subnet which supports public IP's i.e. the route table for the subnet is 0.0.0.0/0 => igw-xxxxxx. The VPC must have "DNS Resolution = yes" and "DNS Hostnames = yes". It should also have DHCP options with the correct "domain-name" for the region, as defined in the docs: http://docs.aws.amazon.com/AmazonVPC/latest/UserGuide/VPC_DHCP_Options.html

```
## VPC Settings
[vpc public]
# ID of the VPC you want to provision cluster into.
vpc_id = vpc-
# ID of the Subnet you want to provision the Master server into
public_subnet = subnet-
# Availability zones of VPC resources
# This is a comma delimited list and must always contain three values
# Example: us-west-2a,NONE,NONE
availability_zones =
```

Once all of those settings contain valid values, you can launch the cluster by repeating the command that was used at the start.
```
$ cfncluster create mycluster
```
Once the cluster reaches the "CREATE_COMPLETE" status, you can connect using your normal SSH client/settings or via the cfncluster CLI.
```
$ cfncluster sshmaster mycluster
```
