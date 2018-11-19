---
name: Bug report
about: Please create a detailed report by completing the following information
labels: 

---

**Environment:**
 - AWS ParallelCluster / CfnCluster version [e.g. aws-parallelcluster-2.0.0]
 - OS: [e.g. alinux]
 - Scheduler: [e.g. SGE]

**Bug description and how to reproduce:**
A clear and concise description of what the bug is and the steps to reproduce the behavior.

**Additional context:**
Any other context about the problem. E.g.:
 - configuration file with credentials or any other personal data removed and pre/post-install scripts if any
 - errors from `/var/log/jobwatcher`, `/var/log/sqswatcher` (Master node) and `/var/log/nodewatcher` (Compute nodes)
 - errors from `/var/cfn-init.log`, `/var/logcloud-init.log` and `/var/log/cloud-init-output.log` files, taken from the Master node after using `--norollback` option to create the cluster
 - screenshots
