=========
CHANGELOG
=========

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