=========
CHANGELOG
=========

develop
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