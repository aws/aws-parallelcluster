=========
CHANGELOG
=========

2.4.1
=====

**ENHANCEMENTS**

* Add support for ap-east-1 region (Hong Kong)
* Add possibility to specify instance type to use when building custom AMIs with ``pcluster createami``
* Speed up cluster creation by having compute nodes starting together with master node
* Enable ASG CloudWatch metrics for the ASG managing compute nodes
* Install Intel MPI 2019u4 on Amazon Linux, Centos 7 and Ubuntu 1604
* Upgrade Elastic Fabric Adapter (EFA) to version 1.4.1 that supports Intel MPI
* Run all node daemons and cookbook recipes in isolated Python virtualenvs. This allows our code to always run with the
  required Python dependencies and solves all conflicts and runtime failures that were being caused by user packages
  installed in the system Python

* Torque:

  * Process nodes added to or removed from the cluster in batches in order to speed up cluster scaling
  * Scale up only if required CPU/nodes can be satisfied
  * Scale down if pending jobs have unsatisfiable CPU/nodes requirements
  * Add support for jobs in hold/suspended state (this includes job dependencies)
  * Automatically terminate and replace faulty or unresponsive compute nodes
  * Add retries in case of failures when adding or removing nodes
  * Add support for ncpus reservation and multi nodes resource allocation (e.g. -l nodes=2:ppn=3+3:ppn=6)
  * Optimized Torque global configuration to faster react to the dynamic cluster scaling

**CHANGES**

* Update EFA installer to a new version, note this changes the location of ``mpicc`` and ``mpirun``.
  To avoid breaking existing code, we recommend you use the modulefile ``module load openmpi`` and ``which mpicc``
  for anything that requires the full path
* Eliminate Launch Configuration and use Launch Templates in all the regions
* Torque: upgrade to version 6.1.2
* Run all ParallelCluster daemons with Python 3.6 in a virtualenv. Daemons code now supports Python >= 3.5

**BUG FIXES**

* Fix issue with sanity check at creation time that was preventing clusters from being created in private subnets
* Fix pcluster configure when relative config path is used
* Make FSx Substack depend on ComputeSecurityGroupIngress to keep FSx from trying to create prior to the SG
  allowing traffic within itself
* Restore correct value for ``filehandle_limit`` that was getting reset when setting ``memory_limit`` for EFA
* Torque: fix compute nodes locking mechanism to prevent job scheduling on nodes being terminated 
* Restore logic that was automatically adding compute nodes identity to SSH ``known_hosts`` file
* Slurm: fix issue that was causing the ParallelCluster daemons to fail when the cluster is stopped and an empty compute nodes file
  is imported in Slurm config


2.4.0
=====

**ENHANCEMENTS**

* Add support for EFA on Centos 7, Amazon Linux and Ubuntu 1604
* Add support for Ubuntu in China region ``cn-northwest-1``

* SGE:

  * process nodes added to or removed from the cluster in batches in order to speed up cluster scaling.
  * scale up only if required slots/nodes can be satisfied
  * scale down if pending jobs have unsatisfiable CPU/nodes requirements
  * add support for jobs in hold/suspended state (this includes job dependencies)
  * automatically terminate and replace faulty or unresponsive compute nodes
  * add retries in case of failures when adding or removing nodes
  * configure scheduler to handle rescheduling and cancellation of jobs running on failing or terminated nodes

* Slurm:

  * scale up only if required slots/nodes can be satisfied
  * scale down if pending jobs have unsatisfiable CPU/nodes requirements
  * automatically terminate and replace faulty or unresponsive compute nodes
  * decrease SlurmdTimeout to 120 seconds to speed up replacement of faulty nodes

* Automatically replace compute instances that fail initialization and dump logs to shared home directory.
* Dynamically fetch compute instance type and cluster size in order to support updates in scaling daemons
* Always use full master FQDN when mounting NFS on compute nodes. This solves some issues occurring with some networking
  setups and custom DNS configurations
* List the version and status during ``pcluster list``
* Remove double quoting of the post_install args
* ``awsbsub``: use override option to set the number of nodes rather than creating multiple JobDefinitions
* Add support for AWS_PCLUSTER_CONFIG_FILE env variable to specify pcluster config file

**CHANGES**

* Update openmpi library to version 3.1.4 on Centos 7, Amazon Linux and Ubuntu 1604. This also changes the default
  openmpi path to ``/opt/amazon/efa/bin/`` and the openmpi module name to ``openmpi/3.1.4``
* Set soft and hard ulimit on open files to 10000 for all supported OSs
* For a better security posture, we're removing AWS credentials from the ``parallelcluster`` config file
  Credentials can be now setup following the canonical procedure used for the aws cli
* When using FSx or EFS do not enforce in sanity check that the compute security group is open to 0.0.0.0/0
* When updating an existing cluster, the same template version is now used, no matter the pcluster cli version
* SQS messages that fail to be processed in ``sqswatcher`` are now re-queued only 3 times and not forever
* Reset ``nodewatcher`` idletime to 0 when the host becomes essential for the cluster (because of min size of ASG or
  because there are pending jobs in the scheduler queue)
* SGE: a node is considered as busy when in one of the following states "u", "C", "s", "d", "D", "E", "P", "o".
  This allows a quick replacement of the node without waiting for the ``nodewatcher`` to terminate it.
* Do not update DynamoDB table on cluster updates in order to avoid hitting strict API limits (1 update per day).

**BUG FIXES**

* Fix issue that was preventing Torque from being used on Centos 7
* Start node daemons at the end of instance initialization. The time spent for post-install script and node
  initialization is not counted as part of node idletime anymore.
* Fix issue which was causing an additional and invalid EBS mount point to be added in case of multiple EBS
* Install Slurm libpmpi/libpmpi2 that is distributed in a separate package since Slurm 17
* ``pcluster ssh`` command now works for clusters with ``use_public_ips = false``
* Slurm: add "BeginTime", "NodeDown", "Priority" and "ReqNodeNotAvail" to the pending reasons that trigger
  a cluster scaling
* Add a timeout on remote commands execution so that the daemons are not stuck if the compute node is unresponsive
* Fix an edge case that was causing the ``nodewatcher`` to hang forever in case the node had become essential to the
  cluster during a call to ``self_terminate``.
* Fix ``pcluster start/stop`` commands when used with an ``awsbatch`` cluster


2.3.1
=====

**ENHANCEMENTS**

* Add support for FSx Lustre with Amazon Linux. In case of custom AMI,
  The kernel will need to be ``>= 4.14.104-78.84.amzn1.x86_64``
* Slurm
   * set compute nodes to DRAIN state before removing them from cluster. This prevents the scheduler from submitting a job to a node that is being terminated.
   * dynamically adjust max cluster size based on ASG settings
   * dynamically change the number of configured FUTURE nodes based on the actual nodes that join the cluster. The max size of the cluster seen by the scheduler always matches the max capacity of the ASG.
   * process nodes added to or removed from the cluster in batches. This speeds up cluster scaling which is able to react with a delay of less than 1 minute to variations in the ASG capacity.
   * add support for job dependencies and pending reasons. The cluster won't scale up if the job cannot start due to an unsatisfied dependency.
   * set ``ReturnToService=1`` in scheduler config in order to recover instances that were initially marked as down due to a transient issue.
* Validate FSx parameters. Fixes `#896 <https://github.com/aws/aws-parallelcluster/issues/896>`_ .

**CHANGES**

* Slurm - Upgrade version to 18.08.6.2
* NVIDIA - update drivers to version 418.56
* CUDA - update toolkit to version 10.0
* Increase default EBS volume size from 15GB to 17GB
* Disabled updates to FSx File Systems, updates to most parameters would cause the filesystem, and all it's data, to be deleted

**BUG FIXES**

* Cookbook wasn't fetched when `custom_ami` parameter specified in the config
* Cfn-init is now fetched from us-east-1, this bug effected non-alinux custom ami's in regions other than us-east-1.
* Account limit check not done for SPOT or AWS Batch Clusters
* Account limit check fall back to master subnet. Fixes `#910 <https://github.com/aws/aws-parallelcluster/issues/910>`_ .
* Boto3 upperbound removed

2.2.1
=====

**ENHANCEMENTS**

* Add support for FSx Lustre in Centos 7. In case of custom AMI, FSx Lustre is
  only supported with Centos 7.5 and Centos 7.6.
* Check AWS EC2 instance account limits before starting cluster creation
* Allow users to force job deletion with ``SGE`` scheduler

**CHANGES**

* Set default value to ``compute`` for ``placement_group`` option
* ``pcluster ssh``: use private IP when the public one is not available
* ``pcluster ssh``: now works also when stack is not completed as long as the master IP is available
* Remove unused dependency on ``awscli`` from ParallelCluster package

**BUG FIXES**

* ``awsbsub``: fix file upload with absolute path
* ``pcluster ssh``: fix issue that was preventing the command from working correctly when stack status is
  ``UPDATE_ROLLBACK_COMPLETE``
* Fix block device conversion to correctly attach EBS nvme volumes
* Wait for Torque scheduler initialization before completing master node setup
* ``pcluster version``: now works also when no ParallelCluster config is present
* Improve ``nodewatcher`` daemon logic to detect if a SGE compute node has running jobs

**DOCS**

* Add documentation on how to use FSx Lustre
* Add tutorial for encrypted EBS with a Custom KMS Key
* Add ``ebs_kms_key_id`` to Configuration section

**TESTING**

* Define a new framework to write and run ParallelCluster integration tests
* Improve scaling integration tests to detect over-scaling
* Implement integration tests for awsbatch scheduler
* Implement integration tests for FSx Lustre file system

2.1.1
=====
* Add China regions `cn-north-1` and `cn-northwest-1`

2.1.0
=====
* Add configuration for RAID 0 and 1 volumes
* Add Elastic File System (EFS) support
* Add AWS Batch Multinode Parallel jobs support
* Add support for Stockholm region (`eu-north-1`)
* Add `--env` and `--env-blacklist` options to the `awsbsub` command to export environment variables
  in the job environment
* Add `--input-file` option to the `awsbsub` command to stage-in input files from the client
* Add new `PCLUSTER_JOB_S3_URL` variable to the job execution environment pointing to the S3 URL used
  for job data stage-in/out
* Add S3 URL for job data staging to the `awsbstat -d` output
* Add `--working-dir` and `--parent-working-dir` options to the `awsbsub` command to specify
  the working-directory or the parent working directory for the job
* Add CPUs and Memory information to the `awsbhosts -d` command

2.0.2
=====
* Add support for GovCloud East, us-gov-east-1 region
* Fix regression with `shared_dir` parameter in the cluster configuration section.
* bugfix:``cfncluster-cookbook``: Fix issue with jq on ubuntu1404 and centos6. Now using version 1.4.
* bugfix:``cfncluster-cookbook``: Fix dependency issue with AWS CLI package on ubuntu1404.

2.0.1
=====
* Fix `configure` and `createami` commands

2.0.0
=====
* Rename CfnCluster to AWS ParallelCluster
* Support multiple EBS Volumes
* Add AWS Batch as a supported scheduler
* Support Custom AMI's

1.6.1
=====
* Fix a bug in `cfncluster configure` introduced in 1.6.0

1.6.0
=====
* Refactor scaling up to take into account the number of pending/requested jobs/slots and instance slots.
* Refactor scaling down to scale down faster and take advantage of per-second billing.
* Add `scaledown_idletime` parameter as part of scale-down refactoring
* Lock hosts before termination to ensure removal of dead compute nodes from host list
* Fix HTTP proxy support

1.5.4
=====
* Add option to disable ganglia `extra_json = { "cfncluster" : { "ganglia_enabled" : "no" } }`
* Fix `cfncluster update` bug
* Set SGE Accounting summary to be true, this reports a single accounting record for a mpi job
* Upgrade cfncluster-node to Boto3

1.5.3
=====
* Add support for GovCloud, us-gov-west-1 region

1.5.2
=====
* feature:``cfncluster``: Added ClusterUser as a stack output. This makes it easier to get the username of the head node.
* feature:``cfncluster``: Added `cfncluster ssh cluster_name`, this allows you to easily ssh into your clusters.
  It allows arbitrary command execution and extra ssh flags to be provided after the command.
  See https://aws-parallelcluster.readthedocs.io/en/latest/commands.html#ssh
* change:``cfncluster``: Moved global cli flags to the command specific flags.
  For example `cfncluster --region us-east-1 create` now becomes `cfncluster create --region us-east-1`
* bugfix:``cfncluster-cookbook``: Fix bug that prevented c5d/m5d instances from working
* bugfix:``cfncluster-cookbook``: Set CPU as a consumable resource in slurm
* bugfix:``cfncluster-node``: Fixed Slurm behavior to add CPU slots so multiple jobs can be scheduled on a single node

1.5.1
=====
* change:``cfncluster``: Added "ec2:DescribeVolumes" permissions to
  CfnClusterInstancePolicy
* change:``cfncluster``: Removed YAML CloudFormation template, it can be
  generated by the https://github.com/awslabs/aws-cfn-template-flip tool

* updates:``cfncluster``: Add support for eu-west-3 region

* feature:``cfncluster-cookbook``: Added parameter to specify custom
  cfncluster-node package

* bugfix:``cfncluster``: Fix --template-url command line parameter
* bugfix:``cfncluster-cookbook``: Poll on EBS Volume attachment status
* bugfix:``cfncluster-cookbook``: Fixed SLURM cron job to publish pending metric
* bugfix:``cfncluster-node``: Fixed Torque behaviour when scaling up from an empty cluster


1.4.2
=====
* bugfix:``cfncluster``: Fix crash when base directory for config file
  does not exist
* bugfix:``cfncluster``: Removed extraneous logging message at
  cfncluster invocation, re-enabled logging in ~/.cfncluster/cfncluster-cli.log
* bugfix: ``cfncluster-node``: Fix scaling issues with CentOS 6 clusters caused
  by incompatible dependencies.
* updates:``ami``: Update all base AMIs to latest patch levels
* updates:``cfncluster-cookbook``: Updated to cfncluster-cookbook-1.4.1

1.4.1
=====
* bugfix:``cfncluster``: Fix abort due to undefinied logger

1.4.0
=====
* change:``cfncluster``: `cfncluster stop` will terminate compute
  instances, but not stop the master node.
* feature:``cfncluster``: CfnCluster no longer maintains a whitelist
  of supported instance types, so new platforms are supported on day
  of launch (including C5).
* bugfix:``cfncluster-cookbook``: Support for NVMe instance store
* updates:``ami``: Update all base AMIs to latest patch levels
* bugfix:``cfncluster-node``: Fixed long scaling times with SLURM

1.3.2
=====
* feature:``cfncluster``: Add support for r2.xlarge/t2.2xlarge,
  x1.16xlarge, r4.*, f1.*, and i3.* instance types
* bugfix:``cfncluster``: Fix support for p2.2xlarge instance type
* feature:``cfncluster``: Add support for eu-west-2, us-east-2, and
  ca-central-1 regions
* updates:``cfncluster-cookbook``: Updated to cfncluster-cookbook-1.3.2
* updates:``ami``: Update all base AMIs to latest patch levels
* updates:``cfncluster``: Moved to Apache 2.0 license
* updates:``cfncluster``: Support for Python 3

1.3.1
=====
* feature:``ami``: Added support for Ubuntu 16.04 LTS
* feature:``ami``: Added NVIDIA 361.42 driver
* feature:``ami``: Added CUDA 7.5
* feature:``cfncluster``: Added support for tags in cluster section in the config
* feature:``cfncluster``: Added support for stopping/starting a cluster
* bugfix:``cfncluster``: Setting DYNAMIC for placement group sanity check fixed
* bugfix:``cfncluster``: Support any type of script for pre/post install
* updates:``cfncluster-cookbook``: Updated to cfncluster-cookbook-1.3.0
* updates:``cfncluster``: Updated docs with more detailed CLI help
* updates:``cfncluster``: Updated docs with development environment setup
* updates:``ami``: Updated to Openlava 3.3.3
* updates:``ami``: Updated to Slurm 16-05-3-1
* updates:``ami``: Updated to Chef 12.13.30
* updates:``ami``: Update all base AMIs to latest patch levels

1.2.1
=====
* bugfix:``cfncluster-node``: Use strings in command for sqswatcher on Python 2.6
* updates:``ami``: Update all base AMIs to latest patch levels

1.2.0
=====
* bugfix:``cfncluster-node``: Correctly set slots per host for Openlava
* updates:``cfncluster-cookbook``: Updated to cfncluster-cookbook-1.2.0
* updates:``ami``: Updated to SGE 8.1.9
* updates:``ami``: Updated to Openlava 3.1.3
* updates:``ami``: Updated to Chef 12.8.1

1.1.0
=====
* feature:``cfncluster``: Support for dynamic placement groups

1.0.1
=====
* bugfix:``cfncluster-node``: Fix for nodes being disabled when maintain_initial_size is true

1.0.0
=====
Official release of the CfnCluster 1.x CLI, templates and AMIs. Available in all regions except BJS, with
support for Amazon Linux, CentOS 6 & 7 and Ubuntu 14.04 LTS. All AMIs are built via packer from the CfnCluster
Cookbook project (https://github.com/aws/aws-parallelcluster-cookbook).

1.0.0-beta
==========

This is a major update for CfnCluster. Boostrapping of the instances has moved from shell scripts into Chef
receipes. Through the use of Chef, there is now wider base OS support, covering Amazon Linux, CentOS 6 & 7
and also Ubuntu. All AMIs are now created using the same receipes. All previously capabilites exisit and the
changes should be non-instrusive.


0.0.22
======
* updates:``ami``: Pulled latest CentOS6 errata
* feature:``cfncluster``: Support for specifiying MasterServer and ComputeFleet root volume size
* bugfix:``cfncluster-node``: Fix for SGE parallel job detection
* bugfix:``ami``: Removed ZFS packages
* bugfix:``cfncluster-node``: Fix torque node additon with pbs_server restart
* updates:``ami``: Updated Chef client to 12.4.1 + berkshelf
* bugfix:``cfncluster``: Only count pending jobs with status 'qw' (Kenneth Daily <kmdaily@gmail.com>)
* bugfix::``cli``: Updated example config file (John Lilley <johnbot@caltech.edu>)
* bugfix::``cli``: Fixed typo on scaling cooldown property (Nelson R Monserrate <MonserrateNelson@JohnDeere.com>)

0.0.21
=======
* feature:``cfncluster``: Support for dedicated tenancy
* feature:``cfncluster``: Support for customer provided KMS keys (EBS and ephemeral)
* updates:``ami``: Pulled latest CentOS6 errata
* feature:``cfncluster``: Support for M4 instances

0.0.20
======
* feature:``cfncluster``: Support for D2 instances
* updates:``ami``: Pulled latest CentOS6 errata
* updates:``ami``: Pulled latest cfncluster-node package
* updates:``ami``: Pulled latest ec2-udev-rules package
* updates:``ami``: Pulled latest NVIDIA driver 346.47
* updates:``ami``: Removed cfncluster-kernel repo and packages
* updates:``ami``: Updated Chef client to 12.2.1 + berkshelf

0.0.19
======
* feature:``cli``: Added configure command; easy config setup
* updates:``docs``: Addtional documentation for configuration options
* updates:``ami``: Pulled latest CentOS6 errata
* bugfix:``cfncluster``: Fixed issue with nodewatcher not scaling down

0.0.18
======
* updates:``ami``: Custom CentOS 6 kernel repo added, support for >32 vCPUs
* feature:``ami``: Chef 11.x client + berkshelf
* feature:``cfncluster``: Support for S3 based pre/post install scripts
* feature:``cfncluster``: Support for EBS shared directory variable
* feature:``cfncluster``: Support for C4 instances
* feature:``cfncluster``: Support for additional VPC security group
* updates:``ami``: Pulled latest NVIDIA driver 340.65
* feature:``cli``: Added support for version command
* updates:``cli``: Removed unimplemented stop command from CLI

0.0.17
======
* updates:``ami``: Pulled latest CentOS errata. Now CentOS 6.6.
* updates:``ami``: Updated SGE to 8.1.6
* updates:``ami``: Updates openlava to latest pull from GitHub
* bugfix:``ami``: Fixed handling of HTTP(S) proxies
* feature:``ami``: Moved sqswatcher and nodewatcher into Python package cfncluster-node

0.0.16
======
* feature:``cfncluster``: Support for GovCloud region
* updates:``cli``: Improved error messages parsing config file

0.0.15
======

* feature:``cfncluster``: Support for Frankfurt region
* feature:``cli``: status call now outputs CREATE_FAILED messages for stacks in error state
* update:``cli``: Improved tags and extra_parameters on CLI
* bugfix:``cli``: Only check config sanity on calls that mutate stack
* updates:``ami``: Pulled latest CentOS errata

0.0.14
======
* feature:``cli``: Introduced sanity_check feature for config
* updates:``cli``: Simplified EC2 key pair config
* feature:``cfncluster``: Scale up is now driven by two policies; enables small and large scaling steps
* feature:``cfnlcuster``: Introduced initial support for CloudWatch logs in us-east-1
* updates:``ami``: Moved deamon handling to supervisord
* updates:``ami``: Pulled latest CentOS errata

0.0.13
======
* bugfix:``cli``: Fixed missing AvailabilityZone for "update" command

0.0.12
======

* updates:``cli``: Simplfied VPC config and removed multi-AZ

0.0.11
======

* updates:``ami``: Pulled latest CentOS errata
* updates:``ami``: Removed DKMS Lustre; replaced with Intel Lustre Client

0.0.10
======

* updates:``ami``: Pulled latest CentOS errata
* updates:``ami``: Updated packages to match base RHEL AMI's
* feature:``cli``: Improved region handling and added support for AWS_DEFAULT_REGION

0.0.9
=====

* feature:``cfncluster``: Added s3_read_resource and s3_read_write_resource options to cluster config
* feature:``cfncluster``: cfncluster is now available in all regions
* updates:``ami``: Pulled latest CentOS errata
* feature:``cfncluster``: Added ephemeral_dir option to cluster config

0.0.8
=====

* feature:``cfncluster``: Added support for new T2 instances
* updates:``cfncluster``: Changed default instance sizes to t2.micro(free tier)
* updates:``cfncluster``: Changed EBS volume default size to 20GB(free tier)
* updates:``ami``: Pulled latest CentOS errata
* bugfix:``cfncluster``: Fixed issues with install_type option(removed)

0.0.7
=====

* feature:``cfncluster``: Added option to encrypt ephemeral drives with in-memory keys
* feature:``cfncluster``: Support for EBS encryption on /shared volume
* feature:``cfncluster``: Detect all ephemeral drives, stripe and mount as /scratch
* feature:``cfncluster``: Support for placement groups
* feature:``cfncluster``: Support for cluster placement logic. Can either be cluster or compute.
* feature:``cfncluster``: Added option to provides arguments to pre/post install scripts
* feature:``cfncluster``: Added DKMS support for Lustre filesystems - http://zfsonlinux.org/lustre.html
* bugfix:``cli``: Added missing support from SSH from CIDR range
* bugfix:``cfncluster``: Fixed Ganglia setup for ComputeFleet
* updates:``SGE``: Updated to 8.1.7 - https://arc.liv.ac.uk/trac/SGE
* updates:``Openlava``: Updated to latest Git for Openlava 2.2 - https://github.com/openlava/openlava

0.0.6
=====

* feature:Amazon EBS: Added support for Amazon EBS General Pupose(SSD) Volumes; both AMI and /shared
* bugfix:``cli``: Fixed boto.exception.NoAuthHandlerFound when using credentials in config
* updates:CentOS: Pulled in latest errata to AMI. See amis.txt for latest ID's.

0.0.5
=====

* Release on GitHub and PyPi
