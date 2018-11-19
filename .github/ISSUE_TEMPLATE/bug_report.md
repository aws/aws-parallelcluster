---
name: Bug report
about: Please create a detailed report by completing the following information
---

**Environment:**
 - AWS ParallelCluster / CfnCluster version [e.g. aws-parallelcluster-2.0.0]
 - OS: [e.g. alinux]
 - Scheduler: [e.g. SGE]

**Bug description and how to reproduce:**
A clear and concise description of what the bug is and the steps to reproduce the behavior.

**Additional context:**
Any other context about the problem. E.g.:
 - configuration file with credentials or any other personal data removed
 - pre/post-install scripts, if any
 - screenshots, if useful
 - if the cluster fails creation, please re-execute `create` action using `--norollback` option and attach `/var/cfn-init.log`, `/var/log/cloud-init.log` and `/var/log/cloud-init-output.log` files from the Master node
 - if you encounter scaling problems please attach `/var/log/nodewatcher` from the Compute node and `/var/log/jobwatcher` and `/var/log/sqswatcher` from the Master node
