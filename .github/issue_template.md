---
name: Issue report
about: Please create a detailed report by completing the following information

---

**Environment:**
 - AWS ParallelCluster / CfnCluster version [e.g. aws-parallelcluster-2.0.0]
 - OS: [e.g. alinux]
 - Scheduler: [e.g. SGE]
 - Master instance type: [e.g. m5.xlarge]
 - Compute instance type: [e.g. c5.8xlarge]

**Bug description and how to reproduce:**
A clear and concise description of what the bug is and the steps to reproduce the behavior.

**Additional context:**
Any other context about the problem. E.g.:
 - configuration file without any credentials or personal data.
 - pre/post-install scripts, if any
 - screenshots, if useful
 - if the cluster fails creation, please re-execute `create` action using `--norollback` option and attach `/var/log/cfn-init.log`, `/var/log/cloud-init.log` and `/var/log/cloud-init-output.log` files from the Master node
 - if you encounter scaling problems please attach `/var/log/nodewatcher` from the Compute node and `/var/log/jobwatcher` and `/var/log/sqswatcher` from the Master node
