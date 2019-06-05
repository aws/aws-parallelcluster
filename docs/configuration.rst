Configuration
=============
.. toctree::

ParallelCluster uses the file ``~/.parallelcluster/config`` by default for all configuration parameters.
You can change the location of the config file via the ``--config`` command option or by setting the
AWS_PARALLELCLUSTER_CONFIG_FILE environment variable.

An example configuration file can be found at ``site-packages/aws-parallelcluster/examples/config``.


Layout
------

Configuration is defined in multiple sections.

Required sections are "global" and "aws".

At least one "cluster" and one "subnet" section must be included.

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
Defines the name of the cluster section used for the cluster.

See the :ref:`Cluster Definition <cluster_definition>`. ::

    cluster_template = default

update_check
""""""""""""
Check for updates to pcluster. ::

    update_check = true

sanity_check
""""""""""""
Attempt to validate the existence of the resources defined in parameters. ::

    sanity_check = true

aws
^^^
AWS credentials/region section.

These settings apply to all clusters and are REQUIRED.

For security purposes, AWS highly recommends using the environment, EC2 IAM Roles, or the
`AWS CLI <https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html>`_ to store credentials rather than saving into the AWS ParallelCluster config file. ::

    [aws]
    aws_access_key_id = #your_aws_access_key_id
    aws_secret_access_key = #your_secret_access_key

    # Defaults to us-east-1 if not defined in environment or below
    aws_region_name = #region

aliases
^^^^^^^
Aliases section.

Customize the `ssh` command here.

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
Defines one or more clusters for different job types or workloads.

Each cluster can have its own individual configuration.

The format is [cluster <clustername>]. ::

    [cluster default]

key_name
""""""""
Name of an existing EC2 KeyPair to enable SSH access to the instances. ::

    key_name = mykey

template_url
""""""""""""
Defines the path to the CloudFormation template used to create the cluster.

Defaults to
``https://s3.amazonaws.com/<aws_region_name>-aws-parallelcluster/templates/aws-parallelcluster-<version>.cfn.json``. ::

    template_url = https://s3.amazonaws.com/us-east-1-aws-parallelcluster/templates/aws-parallelcluster.cfn.json

compute_instance_type
"""""""""""""""""""""
Defines the EC2 instance type used for the cluster compute nodes.

If the scheduler is awsbatch, please refer to the Compute Environments creation in the
AWS Batch UI for the list of supported instance types.

Defaults to t2.micro, ``optimal``  when scheduler is awsbatch ::

    compute_instance_type = t2.micro

master_instance_type
""""""""""""""""""""
Defines the EC2 instance type used for the master node.

Defaults to t2.micro. ::

    master_instance_type = t2.micro

.. _configuration_initial_queue_size:

initial_queue_size
""""""""""""""""""
Set the initial number of EC2 instances to launch as compute nodes in the cluster.

This setting is applicable only for traditional schedulers (sge, slurm, and torque).

If the scheduler is awsbatch, use :ref:`min_vcpus <min_vcpus>`.

Defaults to 2. ::

    initial_queue_size = 2

.. _configuration_max_queue_size:

max_queue_size
""""""""""""""
Set the maximum number of EC2 instances that can be launched in the cluster.

This setting is applicable only for traditional schedulers (sge, slurm, and torque).

If the scheduler is awsbatch, use :ref:`max_vcpus <max_vcpus>`.

Defaults to 10. ::

    max_queue_size = 10

maintain_initial_size
"""""""""""""""""""""
Boolean flag to maintain initial size of the Auto Scaling group for traditional schedulers.

If the scheduler is awsbatch, use :ref:`desired_vcpus <desired_vcpus>`.

If set to true, the Auto Scaling group will never have fewer members than the value
of initial_queue_size.  The cluster can still scale up to the value of max_queue_size.

If set to false, the Auto Scaling group can scale down to 0 members to prevent resources
from sitting idle when they are not needed.

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
Defines the cluster scheduler.

Valid options are sge, torque, slurm, or awsbatch.

If the scheduler is awsbatch, please take a look at the :ref:`networking setup <awsbatch_networking>`.

Defaults to sge. ::

    scheduler = sge

cluster_type
""""""""""""
Defines the type of cluster to launch.

Valid options are ondemand or spot.

Defaults to ondemand. ::

    cluster_type = ondemand

spot_price
""""""""""
If cluster_type is set to spot, you can optionally set the maximum spot price for the
ComputeFleet on traditional schedulers.  If you do not specify a value, you are charged the
Spot price, capped at the On-Demand price.

If the scheduler is awsbatch, use :ref:`spot_bid_percentage <spot_bid_percentage>`.

See the `Spot Bid Advisor <https://aws.amazon.com/ec2/spot/bid-advisor/>`_ for assistance finding a bid price that meets your needs. ::

    spot_price = 1.50

.. _spot_bid_percentage:

spot_bid_percentage
"""""""""""""""""""
If awsbatch is the scheduler, this optional parameter is the on-demand bid percentage.

If unspecified, the current spot market price will be selected, capped at the on-demand price. ::

    spot_bid_percentage = 85

.. _custom_ami_section:

custom_ami
""""""""""
ID of a Custom AMI to use instead of the default `published AMIs <https://github.com/aws/aws-parallelcluster/blob/master/amis.txt>`_. ::

    custom_ami = NONE

s3_read_resource
""""""""""""""""
Specify an S3 resource to which AWS ParallelCluster nodes will be granted read-only access.

For example, 'arn:aws:s3:::my_corporate_bucket/\*' would provide read-only access to all
objects in the my_corporate_bucket bucket.

See :doc:`working with S3 <s3_resources>` for details on format.

Defaults to NONE. ::

    s3_read_resource = NONE

s3_read_write_resource
""""""""""""""""""""""
Specify an S3 resource to which AWS ParallelCluster nodes will be granted read-write access.

For example, 'arn:aws:s3:::my_corporate_bucket/Development/\*' would provide read-write
access to all objects in the Development folder of the my_corporate_bucket bucket.

See :doc:`working with S3 <s3_resources>` for details on format.

Defaults to NONE. ::

    s3_read_write_resource = NONE

pre_install
"""""""""""
URL to a preinstall script that is executed before any of the boot_as_* scripts are run.

When using awsbatch as the scheduler, the preinstall script is only executed on the master node.

The parameter format can be specified as "http://hostname/path/to/script.sh" or "s3://bucketname/path/to/script.sh".

Defaults to NONE. ::

    pre_install = NONE

pre_install_args
""""""""""""""""
Quoted list of arguments to be passed to the preinstall script.

Defaults to NONE. ::

    pre_install_args = NONE

post_install
""""""""""""
URL to a postinstall script that is executed after all of the boot_as_* scripts are run.

When using awsbatch as the scheduler, the postinstall script is only executed on the master node.

Can be specified in "http://hostname/path/to/script.sh" or "s3://bucketname/path/to/script.sh" format.

Defaults to NONE. ::

    post_install = NONE

post_install_args
"""""""""""""""""
Arguments to be passed to the postinstall script.

Defaults to NONE. ::

    post_install_args = NONE

proxy_server
""""""""""""
Defines an HTTP(S) proxy server, typically http://x.x.x.x:8080.

Defaults to NONE. ::

    proxy_server = NONE

placement_group
"""""""""""""""
Defines the cluster placement group.

Valid options are NONE, DYNAMIC or an existing EC2 placement group name.

When DYNAMIC is set, a unique placement group will be created and deleted as part
of the cluster stack.

This parameter does not apply to awsbatch.

More information on placement groups can be found `here <http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/placement-groups.html>`_

Defaults to NONE. ::

    placement_group = NONE

placement
"""""""""
Defines the cluster placement group logic.

This enables the whole cluster or only the compute instances to use the placement group.

Valid options are ``cluster`` or ``compute``.

This parameter does not apply to awsbatch.

Defaults to ``compute``. ::

    placement = compute

ephemeral_dir
"""""""""""""
If instance store volumes exist, define the path where they will be mounted.

Defaults to /scratch. ::

    ephemeral_dir = /scratch

shared_dir
""""""""""
Defines the path where the shared EBS volume will be mounted.

Do not use this option with multiple EBS volumes.  Provide shared_dir under each EBS section instead.

See :ref:`EBS Section <ebs_section>` for details on working with multiple EBS volumes.

Defaults to /shared.

The example below mounts the shared EBS volume at /myshared. ::

    shared_dir = myshared

encrypted_ephemeral
"""""""""""""""""""
Encrypt the ephemeral instance store volumes with non-recoverable in-memory keys
using LUKS (Linux Unified Key Setup).

Please visit https://guardianproject.info/code/luks/ for more information.

Defaults to false. ::

    encrypted_ephemeral = false

master_root_volume_size
"""""""""""""""""""""""
MasterServer root volume size in GB.  The AMI must support growroot.

Defaults to 17, min value 17. ::

    master_root_volume_size = 17

compute_root_volume_size
""""""""""""""""""""""""
ComputeFleet root volume size in GB.  The AMI must support growroot.

Defaults to 17, min value 17. ::

    compute_root_volume_size = 17

base_os
"""""""
OS type used in the cluster.

Available options are: alinux, centos6, centos7, ubuntu1404 and ubuntu1604.

Supported operating systems by region are listed in the table below.  Please note
that commercial entails all supported regions including us-east-1, us-west-2, etc.::

   ============== ======  ============ ============ ============= ============
   region         alinux    centos6       centos7     ubuntu1404   ubuntu1604
   ============== ======  ============ ============ ============= ============
   commercial      True     True          True          True        True
   us-gov-west-1   True     False         False         True        True
   us-gov-east-1   True     False         False         True        True
   cn-north-1      True     False         False         True        True
   cn-northwest-1  True     False         False         False       False
   ============== ======  ============ ============ ============= ============

Note: The base_os determines the username used to log into the cluster.

* CentOS 6 & 7: ``centos``
* Ubuntu 14.04 LTS & 16.04 LTS: ``ubuntu``
* Amazon Linux: ``ec2-user``

Defaults to alinux. ::

    base_os = alinux

ec2_iam_role
""""""""""""
Defines the name of an existing EC2 IAM Role that will be attached to all instances in
the cluster.  Note that the given name of a role and its Amazon Resource Name (ARN) are
different, and the latter may not be used as an argument to ec2_iam_role.

Defaults to NONE. ::

    ec2_iam_role = NONE

extra_json
""""""""""
Extra JSON that will be merged into the dna.json used by Chef.

Defaults to {}. ::

    extra_json = {}

additional_cfn_template
"""""""""""""""""""""""
Defines an additional CloudFormation template to launch along with the cluster.  This
allows for the creation of resources that exist outside of the cluster but are part
of the cluster's life cycle.

This value must be a HTTP URL to a public template with all parameters provided.

Defaults to NONE. ::

    additional_cfn_template = NONE

vpc_settings
""""""""""""
Settings section for the VPC where the cluster will be deployed.

See :ref:`VPC Section <vpc_section>`. ::

    vpc_settings = public

ebs_settings
""""""""""""
Settings section related to the EBS volume mounted on the master instance.  When using
multiple EBS volumes, enter these parameters as a comma separated list.

Up to five (5) additional EBS volumes are supported.

See :ref:`EBS Section <ebs_section>`. ::

  ebs_settings = custom1, custom2, ...

scaling_settings
""""""""""""""""
Settings section relating to autoscaling configuration.

See :ref:`Scaling Section <scaling_section>`. ::

    scaling_settings = custom

efs_settings
""""""""""""
Settings section relating to EFS filesystem.

See :ref:`EFS Section <efs_section>`. ::

    efs_settings = customfs

raid_settings
"""""""""""""
Settings section relating to EBS volume RAID configuration.

See :ref:`RAID Section <raid_section>`. ::

  raid_settings = rs

fsx_settings
""""""""""""
Settings section relating to FSx Lustre configuration.

See :ref:`FSx Section <fsx_section>`. ::

  fsx_settings = fs

tags
""""
Defines tags to be used by CloudFormation.

If command line tags are specified via `--tags`, they will be merged with config tags.

Command line tags overwrite config tags that have the same key.

Tags are JSON formatted and should never have quotes outside the curly braces.

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
ID of the VPC to provision cluster into. ::

    vpc_id = vpc-xxxxxx

master_subnet_id
""""""""""""""""
ID of an existing subnet to provision the Master server into. ::

    master_subnet_id = subnet-xxxxxx

ssh_from
""""""""
CIDR-formatted IP range to allow SSH access from.

This parameter is only used when AWS ParallelCluster creates the security group.

Defaults to 0.0.0.0/0. ::

    ssh_from = 0.0.0.0/0

additional_sg
"""""""""""""
Additional VPC security group Id for all instances.

Defaults to NONE. ::

    additional_sg = sg-xxxxxx

compute_subnet_id
"""""""""""""""""
ID of an existing subnet to provision the compute nodes into.

If the subnet is private, you will need to setup NAT for web access. ::

    compute_subnet_id = subnet-xxxxxx

compute_subnet_cidr
"""""""""""""""""""
If you want AWS ParallelCluster to create a compute subnet, designate the CIDR block here. ::

    compute_subnet_cidr = 10.0.100.0/24

use_public_ips
""""""""""""""
Defines whether or not to assign public IP addresses to compute instances.

If true, an Elastic IP will be associated to the Master instance.

If false, the Master instance will have a Public IP (or not) according to the value
of the "Auto-assign Public IP" subnet configuration parameter.

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
EBS volume configuration settings for the volumes mounted on the master instance and
shared via NFS to the compute nodes. ::

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
Path where the shared EBS volume will be mounted.

This parameter is required when using multiple EBS volumes.

When using one (1) EBS volume, this option will overwrite the shared_dir specified
under the cluster section. The example below mounts to /vol1 ::

    shared_dir = vol1

ebs_snapshot_id
"""""""""""""""
Defines the EBS snapshot Id if using a snapshot as the source for the volume.

Defaults to NONE. ::

    ebs_snapshot_id = snap-xxxxx

volume_type
"""""""""""
The `EBS volume type <http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EBSVolumeTypes.html>`_  of the volume you wish to launch.

Defaults to gp2. ::

    volume_type = io1

volume_size
"""""""""""
Size of volume to be created (if not using a snapshot).

Defaults to 20GB. ::

    volume_size = 20

volume_iops
"""""""""""
Defines the number of IOPS for io1 type volumes. ::

    volume_iops = 200

encrypted
"""""""""
Controls if the EBS volume should be encrypted (note: this should *not* be used with snapshots).

Defaults to false. ::

    encrypted = false

ebs_kms_key_id
""""""""""""""
Use a custom KMS Key for encryption.

This parameter must be used in conjunction with ``encrypted = true`` and needs to
have a custom ``ec2_iam_role``.

See :ref:`Disk Encryption with a Custom KMS Key <tutorials_encrypted_kms_fs>`. ::

    ebs_kms_key_id = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

ebs_volume_id
"""""""""""""
Defines the volume Id of an existing EBS volume that will be attached to the master instance.

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

Suppose you want to launch a cluster with the awsbatch scheduler and let batch pick
the optimal instance type, based on your jobs resource needs.

The following configuration allows a maximum of 40 concurrent vCPUs and scales down
to zero when no jobs have run for 10 minutes. ::

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
Defines configuration settings for the EFS mounted on the master and compute instances. ::

    [efs customfs]
    shared_dir = efs
    encrypted = false
    performance_mode = generalPurpose

shared_dir
""""""""""
Defines the EFS mount point on the master and compute nodes.

This parameter is REQUIRED! The EFS section will only be used if shared_dir is specified.

The example below will mount at /efs.

Do not use NONE or /NONE as the shared directory.::

    shared_dir = efs

encrypted
"""""""""
Defines if the file system will be encrypted.

Defaults to false. ::

    encrypted = false

performance_mode
""""""""""""""""
Defines the Performance Mode of the file system.

Valid choices are generalPurpose or maxIO (these are case-sensitive).

We recommend generalPurpose performance mode for most file systems.

File systems using the maxIO performance mode can scale to higher levels of aggregate
throughput and operations per second with a trade-off of slightly higher latencies for
most file operations.

This parameter cannot be changed after the file system has been created.

Defaults to generalPurpose.::

    performance_mode = generalPurpose

throughput_mode
"""""""""""""""
Defines the Throughput Mode of the file system.

Valid options are bursting and provisioned.::

    throughput_mode = provisioned

provisioned_throughput
""""""""""""""""""""""
Defines the provisioned throughput measured in MiB/s.

This parameter requires setting throughput_mode to provisioned.

The limit on throughput is 1024 MiB/s.  Please contact AWS Support to request a limit increase.

Valid Range: Min of 0.0.::

    provisioned_throughput = 1024

efs_fs_id
"""""""""
Defines the EFS file system ID for an existing file system.

Specifying this option will void all other EFS options except for shared_dir.

config_sanity will only support file systems without a mount target in the stack's
availability zone *or* file systems that have an existing mount target in the stack's
availability zone with inbound and outbound NFS traffic allowed from 0.0.0.0/0.

The sanity check for validating efs_fs_id requires the IAM role to have the following permissions:

efs:DescribeMountTargets
efs:DescribeMountTargetSecurityGroups
ec2:DescribeSubnets
ec2:DescribeSecurityGroups

Please add these permissions to your IAM role or set `sanity_check = false` to avoid errors.

CAUTION: Having mount target with inbound and outbound NFS traffic allowed from 0.0.0.0/0
will expose the file system to NFS mounting request from anywhere in the mount target's
availability zone.  AWS recommends *not* creating a mount target in the stack's availability
zone and letting us handle this step.  If you must have a mount target in the stack's
availability zone, please consider using a custom security group by providing a vpc_security_group_id
option under the vpc section, adding that security group to the mount target, and turning
off config sanity to create the cluster.

Defaults to NONE.::

    efs_fs_id = fs-12345

.. _raid_section:

RAID
^^^^
Defines configuration settings for a RAID array built from a number of identical
EBS volumes.
The RAID drive is mounted on the master node and exported to compute nodes via NFS. ::

    [raid rs]
    shared_dir = raid
    raid_type = 1
    num_of_raid_volumes = 2
    encrypted = true

shared_dir
""""""""""
Defines the mount point for the RAID array on the master and compute nodes.

The RAID drive will only be created if this parameter is specified.

The example below will mount the array at /raid.

Do not use NONE or /NONE as the shared directory.::

    shared_dir = raid

raid_type
"""""""""
Defines the RAID type for the RAID array.

Valid options are RAID 0 or RAID 1.

For more information on RAID types, see: `RAID info
<https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/raid-config.html>`_

The RAID drive will only be created if this parameter is specified.

The example below will create a RAID 0 array::

    raid_type = 0

num_of_raid_volumes
"""""""""""""""""""
Defines the number of EBS volumes to assemble the RAID array from.

Minimum number of volumes = 2.

Maximum number of volumes = 5.

Defaults to 2. ::

    num_of_raid_volumes = 2

volume_type
"""""""""""
Defines the type of volume to build.

See: `Volume type <http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EBSVolumeTypes.html>`_ for more detail.

Defaults to gp2. ::

    volume_type = io1

volume_size
"""""""""""
Defines the size of volume to be created.

Defaults to 20GB. ::

    volume_size = 20

volume_iops
"""""""""""
Defines the number of IOPS for io1 type volumes. ::

    volume_iops = 500

encrypted
"""""""""
Determines if the file system will be encrypted.

Defaults to false. ::

    encrypted = false

ebs_kms_key_id
""""""""""""""
Use a custom KMS Key for encryption.

This must be used in conjunction with ``encrypted = true`` and must have a custom ``ec2_iam_role``.

See :ref:`Disk Encryption with a Custom KMS Key <tutorials_encrypted_kms_fs>`. ::

    ebs_kms_key_id = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx


.. _fsx_section:

FSx
^^^
Configuration for an attached FSx Lustre file system. See `FSx CreateFileSystem
<https://docs.aws.amazon.com/fsx/latest/APIReference/API_CreateFileSystem.html>`_ for more information.

FSx Lustre is supported when ``base_os = centos7 | alinux``.

When using an Amazon Linux ``custom_ami``, the kernel must be >= ``4.14.104-78.84.amzn1.x86_64``.
See `Installing the Lustre Client <https://docs.aws.amazon.com/fsx/latest/LustreGuide/install-lustre-client.html>`_
for instructions.

Note FSx is not currently supported when using ``awsbatch`` as a scheduler.

If using an existing file system, it must be associated to a security group that allows inbound and outbound
TCP traffic from ``0.0.0.0/0`` through port ``988``. This is done by automatically when not using
``vpc_security_group_id``.

Use an existing FSx file system by specifying ``fsx_fs_id``. ::

    [fsx fs]
    shared_dir = /fsx
    fsx_fs_id = fs-073c3803dca3e28a6

Or create and configure a new file system, with the following parameters ::

    [fsx fs]
    shared_dir = /fsx
    storage_capacity = 3600
    import_path = s3://bucket
    imported_file_chunk_size = 1024
    export_path = s3://bucket/folder
    weekly_maintenance_start_time = 1:00:00

shared_dir
""""""""""
**Required** Defines the mount point for the Lustre File system on the master and compute nodes.

The example below will mount the filesystem at /fsx.

Do not use NONE or /NONE as the shared directory.::

    shared_dir = /fsx

fsx_fs_id
"""""""""
**Optional** Attach an existing FSx File System.

If this option is specified, all following FSx parameters, such as ``storage_capacity`` are ignored. ::

    fsx_fs_id = fs-073c3803dca3e28a6

storage_capacity
""""""""""""""""
**Optional** The storage capacity of the file system in GiB.

The storage capacity has a minimum of 3,600 GiB and is provisioned in increments of 3,600 GiB.

Defaults to 3,600 GiB. ::

    storage_capacity = 3600

import_path
"""""""""""
**Optional** S3 Bucket to load data from into the file system. Also serves as the export bucket. See ``export_path``.

Import occurs on cluster creation, see `Importing Data from your Amazon S3 Bucket
<https://docs.aws.amazon.com/fsx/latest/LustreGuide/fsx-data-repositories.html#import-data-repository>`_

If not provided, file system will be empty. ::

    import_path =  s3://bucket

imported_file_chunk_size
""""""""""""""""""""""""
**Optional** For files imported from a data repository (using ``import_path``), this value determines the stripe count
and maximum amount of data per file (in MiB) stored on a single physical disk. The maximum number of disks that a single
file can be striped across is limited by the total number of disks that make up the file system.

The chunk size default is 1,024 MiB (1 GiB) and can go as high as 512,000 MiB (500 GiB).
Amazon S3 objects have a maximum size of 5 TB.

Valid only when using ``import_path``. ::

    imported_file_chunk_size = 1024

export_path
"""""""""""
**Optional** The S3 path where the root of your file system is exported. The path **must** be in the same S3 bucket as
the ``import_path`` parameter.

Defaults to ``s3://import-bucket/FSxLustre[creation-timestamp]`` where ``import-bucket`` is the bucket provided in
``import_path`` parameter.

Valid only when using ``import_path``. ::

    export_path = s3://bucket/folder

weekly_maintenance_start_time
"""""""""""""""""""""""""""""
***Optional** Preferred time to perform weekly maintenance, in UTC time zone.

Format is [day of week]:[hour of day]:[minute of hour]. For example, Monday at Midnight is: ::

    weekly_maintenance_start_time = 1:00:00


