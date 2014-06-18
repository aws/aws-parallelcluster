=========
CHANGELOG
=========

0.0.7
=====

* feature:``cfncluster``: Added option to encrypt ephemeral drives with in-memory keys
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