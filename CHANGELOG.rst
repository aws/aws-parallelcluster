=========
CHANGELOG
=========

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
Offiical release of the CfnCluster 1.x CLI, templates and AMIs. Available in all regions except BJS, with
support for Amazon Linux, CentOS 6 & 7 and Ubuntu 14.04 LTS. All AMIs are built via packer from the CfnCluster
Cookbook project (https://github.com/awslabs/cfncluster-cookbook). 

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
