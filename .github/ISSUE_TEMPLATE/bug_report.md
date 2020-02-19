---
name: Bug report
about: Please create a detailed report by completing the following information
title: ''
labels: ''
assignees: ''

---

**Environment:**
 - AWS ParallelCluster / CfnCluster version [e.g. aws-parallelcluster-2.5.1]
 - Configuration file (i.e. ~/.parallelcluster/config) without any credentials or personal data.

**Bug description and how to reproduce:**
A clear and concise description of what the bug is and the steps to reproduce the behavior.

**Additional context:**
Any other context about the problem. E.g.:
 - pre/post-install scripts, if any
 - screenshots, if useful
 - if the cluster fails creation, please re-execute `create` action using `--norollback` option and attach `/var/log/cfn-init.log`, `/var/log/cloud-init.log` and `/var/log/cloud-init-output.log` files from the Master node
 - if a compute node was terminated due to failure, there will be a directory `/home/logs/compute`. Attach one of the `instance-id.tar.gz` from that directory
 - if you encounter scaling problems please attach `/var/log/nodewatcher` from the Compute node and `/var/log/jobwatcher` and `/var/log/sqswatcher` from the Master node
