Configuration
=============
.. toctree::

pcluster uses the file ``~/.parallelcluster/config`` by default for all configuration parameters.

Please refer to the example configuration file ``site-packages/aws-parallelcluster/examples/config``

Layout
------

Configuration is defined in multiple sections.  Required sections are "global" and "aws".  At least one "cluster" and "subnet" section must be provided.

A section starts with the section name in brackets, followed by parameters and configuration. ::

    [global]
    cluster_template = default
    update_check = true
    sanity_check = true


Configuration Options
---------------------

global
^^^^^^
Global configuration options related to pcluster. ::

    [global]

cluster_template
""""""""""""""""
The name of the cluster section used for the cluster.

See the :ref:`Cluster Definition <cluster_definition>`. ::

    cluster_template = default

update_check
""""""""""""
Determines whether to check for updates to pcluster. ::

    update_check = true

sanity_check
""""""""""""
Attempt to validate that the resources defined in parameters actually exist. ::

    sanity_check = true

aws
^^^
AWS credentials/region section.  These settings apply to all clusters and are REQUIRED.

For security purposes, AWS highly recommends using the environment, EC2 IAM Roles, or the `AWS CLI <https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html>`_ to store credentials rather than storing them in the AWS ParallelCluster config file. ::

    [aws]
    aws_access_key_id = #your_aws_access_key_id
    aws_secret_access_key = #your_secret_access_key

    # Defaults to us-east-1 if not defined in environment or below
    aws_region_name = #region


aliases
^^^^^^^
Aliases section.  Customize the `ssh` command here.

`CFN_USER` is set to the default username for the OS.
`MASTER_IP` is set to the IP address of the master instance.
`ARGS` is set to whatever arguments the user provides after `pcluster ssh cluster_name`. ::

    [aliases]
    # This is the aliases section, you can configure
    # ssh alias here
    ssh = ssh {CFN_USER}@{MASTER_IP} {ARGS}

.. _cluster_definition:

cluster
^^^^^^^
You can define one or more clusters for different types of jobs or workloads.

Each cluster can have its own individual configuration based on your needs.

The format is [cluster <clustername>]. ::

    [cluster default]

key_name
""""""""
Name of an existing EC2 KeyPair to enable SSH access to the instances. ::

    key_name = mykey

template_url
""""""""""""
Setting this value overrides the path to the CloudFormation template used to create the cluster.

Defaults to
``https://s3.amazonaws.com/<aws_region_name>-aws-parallelcluster/templates/aws-parallelcluster-<version>.cfn.json``. ::

    template_url = https://s3.amazonaws.com/us-east-1-aws-parallelcluster/templates/aws-parallelcluster.cfn.json

compute_instance_type
"""""""""""""""""""""
The EC2 instance type used for the cluster compute nodes.

If you are using awsbatch, please refer to the Compute Environments creation in the AWS Batch UI for the list of supported instance types.

Defaults to t2.micro, ``optimal``  when scheduler is awsbatch ::

    compute_instance_type = t2.micro

master_instance_type
""""""""""""""""""""
The EC2 instance type used for the master node.

Defaults to t2.micro. ::

    master_instance_type = t2.micro

.. _configuration_initial_queue_size:

initial_queue_size
""""""""""""""""""
The initial number of EC2 instances to launch as compute nodes in the cluster for traditional schedulers.

If the scheduler is awsbatch, use :ref:`min_vcpus <min_vcpus>`.

Defaults to 2. ::

    initial_queue_size = 2

.. _configuration_max_queue_size:

max_queue_size
""""""""""""""
The maximum number of EC2 instances that can be launched in the cluster for traditional schedulers.

If the scheduler is awsbatch, use :ref:`max_vcpus <max_vcpus>`.

Defaults to 10. ::

    max_queue_size = 10

maintain_initial_size
"""""""""""""""""""""
<<<<<<< HEAD
Boolean flag to maintain initial size of the Auto Scaling group for
traditional schedulers.
=======
Boolean flag to maintain initial size of the Auto Scaling group for traditional schedulers.
>>>>>>> parent of c4d1879... Unified spacing between periods and made some other small phrasing changes.

If the scheduler is awsbatch, use :ref:`desired_vcpus <desired_vcpus>`.

If set to true, the Auto Scaling group will never have fewer members than the value of initial_queue_size.  The cluster can still scale up to the value of max_queue_size.

If set to false, the Auto Scaling group can scale down to 0 members to prevent resources from sitting idle when they
are not needed.

Defaults to false. ::

    maintain_initial_size = false

.. _min_vcpus:

min_vcpus
"""""""""
If the scheduler is awsbatch, the compute environment will never have fewer than min_vcpus.

Defaults to 0. ::

    min_vcpus = 0

.. _desired_vcpus:

desired_vcpus
"""""""""""""
If the scheduler is awsbatch, the compute environment will initially have desired_vcpus.

Defaults to 4. ::

    desired_vcpus = 4

.. _max_vcpus:

max_vcpus
"""""""""
If the scheduler is awsbatch, the compute environment will at most have max_vcpus.

Defaults to 20. ::

    max_vcpus = 20

scheduler
"""""""""
Defines the cluster scheduler.  Valid options are sge, torque, slurm, or awsbatch.

If the scheduler is awsbatch, please take a look at the :ref:`networking setup <awsbatch_networking>`.

Defaults to sge. ::

    scheduler = sge

cluster_type
""""""""""""
Type of cluster to launch.  Valid options are ondemand or spot.

Defaults to ondemand. ::

    cluster_type = ondemand

spot_price
""""""""""
If cluster_type is set to spot, you can optionally set the maximum spot price for the ComputeFleet on traditional schedulers.  If you do not specify a value, you are charged the Spot price, capped at the On-Demand price.

If the scheduler is awsbatch, use :ref:`spot_bid_percentage <spot_bid_percentage>`.

See the `Spot Bid Advisor <https://aws.amazon.com/ec2/spot/bid-advisor/>`_ for assistance finding a bid price that meets your needs::

    spot_price = 1.50

.. _spot_bid_percentage:

spot_bid_percentage
"""""""""""""""""""
If awsbatch is the scheduler, this optional parameter is the on-demand bid percentage.  If unspecified, you will get the current spot market price, capped at the on-demand price. ::

    spot_bid_percentage = 85

.. _custom_ami_section:

custom_ami
""""""""""
ID of a Custom AMI, to use instead of default `published AMIs
<https://github.com/aws/aws-parallelcluster/blob/master/amis.txt>`_. ::

    custom_ami = NONE

s3_read_resource
""""""""""""""""
Specify an S3 resource to which AWS ParallelCluster nodes will be granted read-only access.

For example, 'arn:aws:s3:::my_corporate_bucket/\*' would provide read-only access to all objects in the my_corporate_bucket bucket.

See :doc:`working with S3 <s3_resources>` for details on format.

Defaults to NONE. ::

    s3_read_resource = NONE

s3_read_write_resource
""""""""""""""""""""""
Specify S3 resource for which AWS ParallelCluster nodes will be granted read-write access

<<<<<<< HEAD
For example, 'arn:aws:s3:::my_corporate_bucket/Development/\*' would provide
read-write access to all objects in the Development folder of the
my_corporate_bucket bucket.
=======
For example, 'arn:aws:s3:::my_corporate_bucket/Development/\*' would provide read-write access to all objects in the Development folder of the my_corporate_bucket bucket.
>>>>>>> parent of c4d1879... Unified spacing between periods and made some other small phrasing changes.

See :doc:`working with S3 <s3_resources>` for details on format.

Defaults to NONE. ::

    s3_read_write_resource = NONE

pre_install
"""""""""""
URL to a preinstall script that is executed before any of the boot_as_* scripts are run.  When using awsbatch as the scheduler, the preinstall script is only executed on the master node.

Can be specified in "http://hostname/path/to/script.sh" or "s3://bucketname/path/to/script.sh" format.

Defaults to NONE. ::

    pre_install = NONE

pre_install_args
""""""""""""""""
Quoted list of arguments to be passed to preinstall script.

Defaults to NONE. ::

    pre_install_args = NONE

post_install
""""""""""""
URL to a postinstall script that is executed after all of the boot_as_* scripts are run.  This is only executed on the master node when using awsbatch as the scheduler.

Can be specified in "http://hostname/path/to/script.sh" or "s3://bucketname/path/to/script.sh" format.

Defaults to NONE. ::

    post_install = NONE

post_install_args
"""""""""""""""""
Arguments to be passed to postinstall script.

Defaults to NONE. ::

    post_install_args = NONE

proxy_server
""""""""""""
HTTP(S) proxy server, typically http://x.x.x.x:8080

Defaults to NONE. ::

    proxy_server = NONE

placement_group
"""""""""""""""
Cluster placement group. The can be one of three values: NONE, DYNAMIC and an existing placement group name.  When DYNAMIC is set, a unique placement group will be created as part of the cluster and deleted when the cluster is deleted.

This does not apply to awsbatch.

Defaults to NONE. More information on placement groups can be found `here
<http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/placement-groups.html>`_::

    placement_group = NONE

placement
"""""""""
Cluster placement logic. This enables the whole cluster or only the compute instances to use the placement group.  Valid options are ``cluster`` or ``compute``.

This does not apply to awsbatch.

Defaults to ``compute``. ::

    placement = compute

ephemeral_dir
"""""""""""""
If instance store volumes exist, this is the path/mountpoint where they will be mounted.

Defaults to /scratch. ::

    ephemeral_dir = /scratch

shared_dir
""""""""""
Path/mountpoint for shared EBS volume. Do not use this option when using
multiple EBS volumes; provide shared_dir under each EBS section instead.

Defaults to /shared.
The example below mounts the shared EBS volume at /myshared. See :ref:`EBS Section <ebs_section>` for details on working with multiple EBS volumes::

    shared_dir = myshared

encrypted_ephemeral
"""""""""""""""""""
Encrypted ephemeral drives. In-memory keys, non-recoverable. If true, AWS ParallelCluster will generate an ephemeral encryption key in memory and encrypt your instance store volumes using LUKS.

Defaults to false. ::

    encrypted_ephemeral = false

master_root_volume_size
"""""""""""""""""""""""
MasterServer root volume size in GB.  AMI must support growroot.

Defaults to 15. ::

    master_root_volume_size = 15

compute_root_volume_size
""""""""""""""""""""""""
ComputeFleet root volume size in GB.  AMI must support growroot.

Defaults to 15. ::

    compute_root_volume_size = 15

base_os
"""""""
OS type used in the cluster.

Available options are: alinux, centos6, centos7, ubuntu1404 and ubuntu1604.

Defaults to alinux.

Note: The base_os determines the username used to log into the cluster.

Supported operating systems by region. Please note that commercial entails all supported regions including us-east-1, us-west-2 etc. ::

    ============== ======  ============ ============ ============= ============
    region         alinux    centos6       centos7     ubuntu1404   ubuntu1604
    ============== ======  ============ ============ ============= ============
    commercial      True     True          True          True        True
    us-gov-west-1   True     False         False         True        True
    us-gov-east-1   True     False         False         True        True
    cn-north-1      True     False         False         True        True
    cn-northwest-1  True     False         False         False       False
    ============== ======  ============ ============ ============= ============

* CentOS 6 & 7: ``centos``
* Ubuntu: ``ubuntu``
* Amazon Linux: ``ec2-user`` ::

    base_os = alinux

ec2_iam_role
""""""""""""
The given name of an existing EC2 IAM Role that will be attached to all instances in the cluster.  Note that the given name of a role and its Amazon Resource Name (ARN) are different, and the latter can not be used as an argument to ec2_iam_role.

Defaults to NONE. ::

    ec2_iam_role = NONE

extra_json
""""""""""
Extra JSON that will be merged into the dna.json used by Chef.

Defaults to {}. ::

    extra_json = {}

additional_cfn_template
"""""""""""""""""""""""
An additional CloudFormation template to launch along with the cluster.  This
allows for the creation of resources that exist outside of the cluster but are part of the cluster's life cycle.

Must be a HTTP URL to a public template with all parameters provided.

Defaults to NONE. ::

    additional_cfn_template = NONE


vpc_settings
""""""""""""
Settings section relating to VPC to be used.

See :ref:`VPC Section <vpc_section>`. ::

    vpc_settings = public

ebs_settings
""""""""""""
Settings section relating to EBS volume mounted on the master.  When using multiple EBS volumes, enter multiple settings as a comma separated list. Up to 5 EBS volumes are supported.

See :ref:`EBS Section <ebs_section>`. ::

  ebs_settings = custom1, custom2, ...

scaling_settings
""""""""""""""""
Settings section relation to scaling.

See :ref:`Scaling Section <scaling_section>`. ::

    scaling_settings = custom

efs_settings
""""""""""""
Settings section relating to EFS filesystem.

See :ref:`EFS Section <efs_section>`. ::

    efs_settings = customfs

raid_settings
"""""""""""""
Settings section relating to RAID drive configuration.

See :ref:`RAID Section <raid_section>`. ::

  raid_settings = rs

tags
""""
Defines tags to be used in CloudFormation.

If command line tags are specified via `--tags`, they will be merged with config tags.

Command line tags overwrite config tags that have the same key.

Tags are JSON formatted and should never have quotes outside the curly braces.

See `AWS CloudFormation Resource Tags Type
<https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-resource-tags.html>`_. ::

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

This is only used when AWS ParallelCluster creates the security group.

Defaults to 0.0.0.0/0. ::

    ssh_from = 0.0.0.0/0

additional_sg
"""""""""""""
Additional VPC security group Id for all instances.

Defaults to NONE. ::

    additional_sg = sg-xxxxxx

compute_subnet_id
"""""""""""""""""
ID of an existing subnet you want to provision the compute nodes into.

If it is private, you need to setup NAT for web access. ::

    compute_subnet_id = subnet-xxxxxx

compute_subnet_cidr
"""""""""""""""""""
If you wish for AWS ParallelCluster to create a compute subnet, designate the CIDR here. ::

    compute_subnet_cidr = 10.0.100.0/24

use_public_ips
""""""""""""""
Define whether or not to assign public IP addresses to Compute EC2 instances.

If true, an Elastic IP will be associated to the Master instance.
If false, the Master instance will have a Public IP or not according to the value of the "Auto-assign Public IP" subnet configuration parameter.

See :ref:`networking configuration <networking>` for some examples.

Defaults to true. ::

    use_public_ips = true

vpc_security_group_id
"""""""""""""""""""""
Use an existing security group for all instances.

Defaults to NONE. ::

    vpc_security_group_id = sg-xxxxxx

.. _ebs_section:

ebs
^^^
EBS Volume configuration settings for the volumes mounted on the master node and shared via NFS to compute nodes. ::

    [ebs custom1]
    shared_dir = vol1
    ebs_snapshot_id = snap-xxxxx
    volume_type = io1
    volume_iops = 200
    ...

    [ebs custom2]
    shared_dir = vol2
    ...

    ...

shared_dir
""""""""""
Path/mountpoint for shared EBS volume. Required when using multiple EBS volumes.  When using 1 ebs volume, this option will overwrite the shared_dir specified under the cluster section. The example below mounts to /vol1 ::

    shared_dir = vol1

ebs_snapshot_id
"""""""""""""""
Id of EBS snapshot if using snapshot as source for volume.

Defaults to NONE. ::

    ebs_snapshot_id = snap-xxxxx

volume_type
"""""""""""
The `API name <http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EBSVolumeTypes.html>`_  for the type of volume you wish to launch.

Defaults to gp2. ::

    volume_type = io1

volume_size
"""""""""""
Size of volume to be created (if not using a snapshot).

Defaults to 20GB. ::

    volume_size = 20

volume_iops
"""""""""""
Number of IOPS for io1 type volumes. ::

    volume_iops = 200

encrypted
"""""""""
Controls if the volume should be encrypted (note: this should *not* be used with snapshots).

Defaults to false. ::

    encrypted = false

ebs_kms_key_id
""""""""""""""
Use a custom KMS Key for encryption. This must be used in conjunction with ``encrypted = true`` and needs to have a custom ``ec2_iam_role``. See `Encrypted EBS with a Custom KMS Key <_encrypted_ebs>`. ::

    ebs_kms_key_id = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

ebs_volume_id
"""""""""""""
EBS Volume Id of an existing volume that will be attached to the MasterServer.

Defaults to NONE. ::

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

This does not apply to awsbatch.

Defaults to 10. ::

    scaledown_idletime = 10


examples
^^^^^^^^

Suppose you want to launch a cluster with the awsbatch scheduler and let batch pick the optimal instance type, based on your jobs resource needs.

The following allows a maximum of 40 concurrent vCPUs, and scales down to zero when you have no jobs running for 10 minutes. ::

  [global]
  update_check = true
  sanity_check = true
  cluster_template = awsbatch

  [aws]
  aws_region_name = [your_aws_region]

  [cluster awsbatch]
  scheduler = awsbatch
  compute_instance_type = optimal # optional, defaults to optimal
  min_vcpus = 0                   # optional, defaults to 0
  desired_vcpus = 0               # optional, defaults to 4
  max_vcpus = 40                  # optional, defaults to 20
  base_os = alinux                # optional, defaults to alinux, controls the base_os of the master instance and the docker image for the compute fleet
  key_name = [your_ec2_keypair]
  vpc_settings = public

  [vpc public]
  master_subnet_id = [your_subnet]
  vpc_id = [your_vpc]

.. spelling::
    alinux
    ami
    arn
    aws
    bucketname
    centos
    cfn
    cidr
    cli
    clustername
    dna
    ebs
    ec
    gp
    iam
    idletime
    io
    iops
    ip
    ips
    mountpoint
    myshared
    ondemand
    os
    postinstall
    pre
    preinstall
    scaledown
    sg
    sge
    slurm
    ubuntu
    url
    vcpus
    vpc

.. _efs_section:

EFS
^^^
EFS file system configuration settings for the EFS mounted on the master node and compute nodes via nfs4. ::


    [efs customfs]
    shared_dir = efs
    encrypted = false
    performance_mode = generalPurpose

shared_dir
""""""""""
Shared directory that the file system will be mounted to on the master and compute nodes.

<<<<<<< HEAD
This parameter is REQUIRED, the EFS section will only be used if this
parameter is specified.
The below example mounts to /efs.
Do not use NONE or /NONE as the shared directory.::
=======
This parameter is REQUIRED, the EFS section will only be used if this parameter is specified.
The below example mounts to /efs. Do not use NONE or /NONE as the shared directory.::
>>>>>>> parent of c4d1879... Unified spacing between periods and made some other small phrasing changes.

    shared_dir = efs

encrypted
"""""""""
Whether or not the file system will be encrypted.

Defaults to false. ::

    encrypted = false

performance_mode
""""""""""""""""
Performance Mode of the file system. We recommend generalPurpose performance mode for most file systems.  File systems using the maxIO performance mode can scale to higher levels of aggregate throughput and operations per second with a trade-off of slightly higher latencies for most file operations.  This cannot be changed after the file system has been created.

Defaults generalPurpose. Valid Values are generalPurpose | maxIO (case sensitive). ::

    performance_mode = generalPurpose

throughput_mode
"""""""""""""""
The throughput mode for the file system to be created.  There are two throughput modes to choose from for your file system: bursting and provisioned.

    throughput_mode = provisioned

provisioned_throughput
""""""""""""""""""""""
The throughput, measured in MiB/s, that you want to provision for a file system that you are creating.  The limit on throughput is 1024 MiB/s. You can get these limits increased by contacting AWS Support.

Valid Range: Min of 0.0.  To use this option, you must set the throughput_mode to provisioned ::

    provisioned_throughput = 1024

efs_fs_id
"""""""""
File system ID for an existing file system. Specifying this option will void all other EFS options but shared_dir.  Config sanity will only allow file systems that: have no mount target in the stack's availability zone OR have existing mount target in stack's availability zone with inbound and outbound NFS traffic allowed from 0.0.0.0/0.

Note: sanity check for validating efs_fs_id requires the IAM role to have permission for the following actions: efs:DescribeMountTargets, efs:DescribeMountTargetSecurityGroups, ec2:DescribeSubnets, ec2:DescribeSecurityGroups.

Please add these permissions to your IAM role, or set `sanity_check = false` to avoid errors.

CAUTION: having mount target with inbound and outbound NFS traffic allowed from 0.0.0.0/0 will expose the file system to NFS mounting request from anywhere in the mount target's availability zone.  We recommend not to have a mount target in stack's availability zone and let us create the mount target.  If you must have a mount target in stack's availability zone, consider using a custom security group by providing a vpc_security_group_id option under the vpc section, adding that security group to the mount target, and turning off config sanity to create the cluster.

Defaults to NONE. Needs to be an available EFS file system::

    efs_fs_id = fs-12345


.. _raid_section:

RAID
^^^^
RAID drive configuration settings for creating a RAID array from a number of identical EBS volumes. The RAID drive
is mounted on the master node, and exported to compute nodes via nfs. ::


    [raid rs]
    shared_dir = raid
    raid_type = 1
    num_of_raid_volumes = 2
    encrypted = true

shared_dir
""""""""""
Shared directory that the RAID drive will be mounted to on the master and compute nodes.

This parameter is REQUIRED, the RAID drive will only be created if this parameter is specified.
The below example mounts to /raid. Do not use NONE or /NONE as the shared directory.::

    shared_dir = raid

raid_type
"""""""""
RAID type for the RAID array. Currently only support RAID 0 or RAID 1. For more information on RAID types, see: `RAID info <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/raid-config.html>`_

This parameter is REQUIRED, the RAID drive will only be created if this parameter is specified.
The below example will create a RAID 0 array::

    raid_type = 0

num_of_raid_volumes
"""""""""""""""""""
The number of EBS volumes to assemble the RAID array from. Currently supports max of 5 volumes and minimum of 2.

Defaults to 2. ::

    num_of_raid_volumes = 2

volume_type
"""""""""""
The the type of volume you wish to launch.
See: `Volume type <http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EBSVolumeTypes.html>`_ for detail

Defaults to gp2. ::

    volume_type = io1

volume_size
"""""""""""
Size of volume to be created.

Defaults to 20GB. ::

    volume_size = 20

volume_iops
"""""""""""
Number of IOPS for io1 type volumes. ::

    volume_iops = 500

encrypted
"""""""""
Determines if the file system will be encrypted.

Defaults to false. ::

    encrypted = false

ebs_kms_key_id
""""""""""""""
Use a custom KMS Key for encryption.  This must be used in conjunction with ``encrypted = true`` and needs to have a custom ``ec2_iam_role``. See `Encrypted EBS with a Custom KMS Key <_encrypted_ebs>`. ::

    ebs_kms_key_id = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
