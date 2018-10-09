Configuration
=============
.. toctree::

cfncluster uses the file ``~/.cfncluster/config`` by default for all configuration parameters.

You can see an example configuration file ``site-packages/cfncluster/examples/config``

Layout
------

Configuration is defined in multiple sections.  Required sections are "global", "aws", one "cluster", and one "subnet".

A section starts with the section name in brackets, followed by parameters and configuration. ::

    [global]
    cluster_template = default
    update_check = true
    sanity_check = true


Configuration Options
---------------------

global
^^^^^^
Global configuration options related to cfncluster. ::

    [global]

cluster_template
""""""""""""""""
The name of the cluster section used for the cluster.

See the :ref:`Cluster Definition <cluster_definition>`. ::

    cluster_template = default

update_check
""""""""""""
Whether or not to check for updates to cfncluster. ::

    update_check = true

sanity_check
""""""""""""
Attempts to validate that resources defined in parameters actually exist. ::

    sanity_check = true

aws
^^^
This is the AWS credentials/region section (required).  These settings apply to all clusters.

We highly recommend use of the environment, EC2 IAM Roles, or storing credentials using the `AWS CLI <https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html>`_ to store credentials, rather than storing them in the CfnCluster config file. ::

    [aws]
    aws_access_key_id = #your_aws_access_key_id
    aws_secret_access_key = #your_secret_access_key

    # Defaults to us-east-1 if not defined in environment or below
    aws_region_name = #region


aliases
^^^^^^^
This is the aliases section. Use this section to customize the `ssh` command.

`CFN_USER` is set to the default username for the os.
`MASTER_IP` is set to the ip address of the master instance.
`ARGS` is set to whatever arguments the user provides after `cfncluster ssh cluster_name`. ::

    [aliases]
    # This is the aliases section, you can configure
    # ssh alias here
    ssh = ssh {CFN_USER}@{MASTER_IP} {ARGS}

.. _cluster_definition:

cluster
^^^^^^^
You can define one or more clusters for different types of jobs or workloads.

Each cluster has it's own configuration based on your needs.

The format is [cluster <clustername>]. ::

    [cluster default]

key_name
""""""""
Name of an existing EC2 KeyPair to enable SSH access to the instances. ::

    key_name = mykey

template_url
""""""""""""
Overrides the path to the cloudformation template used to create the cluster

Defaults to ``https://s3.amazonaws.com/<aws_region_name>-cfncluster/templates/cfncluster-<version>.cfn.json``. ::

    template_url = https://s3.amazonaws.com/us-east-1-cfncluster/templates/cfncluster.cfn.json

compute_instance_type
"""""""""""""""""""""
The EC2 instance type used for the cluster compute nodes.

Defaults to t2.micro for default template. ::

    compute_instance_type = t2.micro

master_instance_type
""""""""""""""""""""
The EC2 instance type use for the master node.

This defaults to t2.micro for default template. ::

    master_instance_type = t2.micro

initial_queue_size
""""""""""""""""""
The initial number of EC2 instances to launch as compute nodes in the cluster.

The default is 2 for default template. ::

    initial_queue_size = 2

max_queue_size
""""""""""""""
The maximum number of EC2 instances that can be launched in the cluster.

This defaults to 10 for the default template. ::

    max_queue_size = 10

maintain_initial_size
"""""""""""""""""""""
Boolean flag to set autoscaling group to maintain initial size.

If set to true, the Auto Scaling group will never have fewer members than the value of initial_queue_size.  It will still allow the cluster to scale up to the value of max_queue_size.

Setting to false allows the Auto Scaling group to scale down to 0 members, so resources will not sit idle when they aren't needed.

Defaults to false for the default template. ::

    maintain_initial_size = false

scheduler
"""""""""
Scheduler to be used with the cluster.  Valid options are sge, torque, or slurm.

Defaults to sge for the default template. ::

    scheduler = sge

cluster_type
""""""""""""
Type of cluster to launch i.e. ondemand or spot

Defaults to ondemand for the default template. ::

    cluster_type = ondemand

spot_price
"""""""""""
If cluster_type is set to spot, you can optionally set the maximum spot price for the ComputeFleet. If you do not specify a value, you are charged the Spot price, capped at the On-Demand price.

See the `Spot Bid Advisor <https://aws.amazon.com/ec2/spot/bid-advisor/>`_ for assistance finding a bid price that meets your needs::

    spot_price = 0.00

.. _custom_ami_section:

custom_ami
""""""""""
ID of a Custom AMI, to use instead of default `published AMI's <https://github.com/awslabs/cfncluster/blob/master/amis.txt>`_. ::

    custom_ami = NONE

s3_read_resource
""""""""""""""""
Specify S3 resource for which cfncluster nodes will be granted read-only access

For example, 'arn:aws:s3:::my_corporate_bucket/\*' would provide read-only access to all objects in the my_corporate_bucket bucket.

See :doc:`working with S3 <s3_resources>` for details on format.

Defaults to NONE for the default template. ::

    s3_read_resource = NONE

s3_read_write_resource
""""""""""""""""""""""
Specify S3 resource for which cfncluster nodes will be granted read-write access

For example, 'arn:aws:s3:::my_corporate_bucket/Development/\*' would provide read-write access to all objects in the Development folder of the my_corporate_bucket bucket.

See :doc:`working with S3 <s3_resources>` for details on format.

Defaults to NONE for the default template. ::

    s3_read_write_resource = NONE

pre_install
"""""""""""
URL to a preinstall script. This is executed before any of the boot_as_* scripts are run

Can be specified in "http://hostname/path/to/script.sh" or "s3://bucketname/path/to/script.sh" format.

Defaults to NONE for the default template. ::

    pre_install = NONE

pre_install_args
""""""""""""""""
Quoted list of arguments to be passed to preinstall script

Defaults to NONE for the default template. ::

    pre_install_args = NONE

post_install
""""""""""""
URL to a postinstall script. This is executed after any of the boot_as_* scripts are run

Can be specified in "http://hostname/path/to/script.sh" or "s3://bucketname/path/to/script.sh" format.

Defaults to NONE for the default template. ::

    post_install = NONE

post_install_args
"""""""""""""""""
Arguments to be passed to postinstall script

Defaults to NONE for the default template. ::

    post_install_args = NONE

proxy_server
""""""""""""
HTTP(S) proxy server, typically http://x.x.x.x:8080

Defaults to NONE for the default template. ::

    proxy_server = NONE

placement_group
"""""""""""""""
Cluster placement group. The can be one of three values: NONE, DYNAMIC and an existing placement group name. When DYNAMIC is set, a unique placement group will be created as part of the cluster and deleted when the cluster is deleted.

Defaults to NONE for the default template. More information on placement groups can be found `here <http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/placement-groups.html>`_::

    placement_group = NONE

placement
"""""""""
Cluster placement logic. This enables the whole cluster or only compute to use the placement group.

Defaults to cluster in the default template. ::

    placement = cluster

ephemeral_dir
"""""""""""""
If instance store volumes exist, this is the path/mountpoint they will be mounted on.

Defaults to /scratch in the default template. ::

    ephemeral_dir = /scratch

shared_dir
""""""""""
Path/mountpoint for shared EBS volume

Defaults to /shared in the default template. See :ref:`EBS Section <ebs_section>` for details on working with EBS volumes::

    shared_dir = /shared

encrypted_ephemeral
"""""""""""""""""""
Encrypted ephemeral drives. In-memory keys, non-recoverable. If true, CfnCluster will generate an ephemeral encryption key in memroy and using LUKS encryption, encrypt your instance store volumes.

Defaults to false in default template. ::

    encrypted_ephemeral = false

master_root_volume_size
"""""""""""""""""""""""
MasterServer root volume size in GB. (AMI must support growroot)

Defaults to 15 in default template. ::

    master_root_volume_size = 15

compute_root_volume_size
""""""""""""""""""""""""
ComputeFleet root volume size in GB. (AMI must support growroot)

Defaults to 15 in default template. ::

    compute_root_volume_size = 15

base_os
"""""""
OS type used in the cluster

Defaults to alinux in the default template. Available options are: alinux, centos6, centos7, ubuntu1404 and ubuntu1604

Note: The base_os determines the username used to log into the cluster.

* Centos 6 & 7: ``centos``
* Ubuntu: ``ubuntu``
* Amazon Linux: ``ec2-user`` ::

    base_os = alinux

ec2_iam_role
""""""""""""
The given name of an existing EC2 IAM Role that will be attached to all
instances in the cluster. Note that the given name of a role and its Amazon
Resource Name (ARN) are different, and the latter can not be used as an argument
to ec2_iam_role.

Defaults to NONE in the default template. ::

    ec2_iam_role = NONE

extra_json
""""""""""
Extra JSON that will be merged into the dna.json used by Chef.

Defaults to {} in the default template. ::

    extra_json = {}

additional_cfn_template
"""""""""""""""""""""""
An additional CloudFormation template to launch along with the cluster. This allows you to create resources that exist outside of the cluster but are part of the cluster's lifecycle.

Must be a HTTP URL to a public template with all parameters provided.

Defaults to NONE in the default template. ::

    additional_cfn_template = NONE


vpc_settings
""""""""""""
Settings section relating to VPC to be used

See :ref:`VPC Section <vpc_section>`. ::

    vpc_settings = public

ebs_settings
""""""""""""
Settings section relating to EBS volume mounted on the master.

See :ref:`EBS Section <ebs_section>`. ::

  ebs_settings = custom

scaling_settings
""""""""""""""""
Settings section relation to scaling

See :ref:`Scaling Section <scaling_section>`. ::

    scaling_settings = custom

tags
""""
Defines tags to be used in CloudFormation.

If command line tags are specified via `--tags`, they get merged with config tags.

Command line tags overwrite config tags that have the same key.

Tags are JSON formatted and should not have quotes outside the curly braces.

See `AWS CloudFormation Resource Tags Type <https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-resource-tags.html>`_. ::

    tags = {"key" : "value", "key2" : "value2"}

.. _vpc_section:

vpc
^^^
VPC Configuration Settings::

    [vpc public]
    vpc_id = vpc-xxxxxx
    master_subnet_id = subnet-xxxxxx

vpc_id
""""""
ID of the VPC you want to provision cluster into. ::

    vpc_id = vpc-xxxxxx

master_subnet_id
""""""""""""""""
ID of an existing subnet you want to provision the Master server into. ::

    master_subnet_id = subnet-xxxxxx

ssh_from
""""""""
CIDR formatted IP range in which to allow SSH access from.

This is only used when cfncluster creates the security group.

Defaults to 0.0.0.0/0 in the default template. ::

    ssh_from = 0.0.0.0/0

additional_sg
"""""""""""""
Additional VPC security group Id for all instances.

Defaults to NONE in the default template. ::

    additional_sg = sg-xxxxxx

compute_subnet_id
"""""""""""""""""
ID of an existing subnet you want to provision the compute nodes into.

If it is private, you need to setup NAT for web access. ::

    compute_subnet_id = subnet-xxxxxx

compute_subnet_cidr
"""""""""""""""""""
If you wish for cfncluster to create a compute subnet, this is the CIDR that. ::

    compute_subnet_cidr = 10.0.100.0/24

use_public_ips
""""""""""""""
Define whether or not to assign public IP addresses to Compute EC2 instances.

If true, an Elastic Ip will be associated to the Master instance.
If false, the Master instance will have a Public IP or not according to the value
of the "Auto-assign Public IP" subnet configuration parameter.

See `networking configuration <https://cfncluster.readthedocs.io/en/latest/networking.html>`_ for some examples.

Defaults to true. ::

    use_public_ips = true

vpc_security_group_id
"""""""""""""""""""""
Use an existing security group for all instances.

Defaults to NONE in the default template. ::

    vpc_security_group_id = sg-xxxxxx

.. _ebs_section:

ebs
^^^
EBS Volume configuration settings for the volume mounted on the master node and shared via NFS to compute nodes. ::

    [ebs custom]
    ebs_snapshot_id = snap-xxxxx
    volume_type = io1
    volume_iops = 200

ebs_snapshot_id
"""""""""""""""
Id of EBS snapshot if using snapshot as source for volume.

Defaults to NONE for default template. ::

    ebs_snapshot_id = snap-xxxxx

volume_type
"""""""""""
The `API name <http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EBSVolumeTypes.html>`_  for the type of volume you wish to launch.

Defaults to gp2 for default template. ::

    volume_type = io1

volume_size
"""""""""""
Size of volume to be created (if not using a snapshot).

Defaults to 20GB for default template. ::

    volume_size = 20

volume_iops
"""""""""""
Number of IOPS for io1 type volumes. ::

    volume_iops = 200

encrypted
"""""""""
Whether or not the volume should be encrypted (should not be used with snapshots).

Defaults to false for default template. ::

    encrypted = false

ebs_volume_id
"""""""""""""
EBS Volume Id of an existing volume that will be attached to the MasterServer.

Defaults to NONE for default template. ::

    ebs_volume_id = vol-xxxxxx

.. _scaling_section:

scaling
^^^^^^^
Settings which define how the compute nodes scale. ::


    [scaling custom]
    scaledown_idletime = 10

scaledown_idletime
""""""""""""""""""
Amount of time in minutes without a job after which the compute node will terminate.

Defaults to 10 for the default template. ::

    scaledown_idletime = 10
