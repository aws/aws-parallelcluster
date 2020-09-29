---
name: Bug report
about: Please create a detailed report by completing the following information
title: ''
labels: ''
assignees: ''

---

If you are reporting an issue with AWS Parallelcluster / CfnCluster please make sure to add the following data in order to facilitate the root cause detection:

**Required Info:**
 - AWS ParallelCluster version [e.g. 2.9.0]:
 - Full cluster configuration without any credentials or personal data
 - Cluster name:
 - [Optional] Arn of the cluster CloudFormation main stack:

**Bug description and how to reproduce:**
A clear and concise description of what the bug is and the steps to reproduce the behavior.

**If you are reporting issues about scaling or job failure:**
We cannot work on issues without proper logs. We **STRONGLY** recommend following [this guide](https://github.com/aws/aws-parallelcluster/wiki/Creating-an-Archive-of-a-Cluster's-Logs) and attach the complete cluster log archive with the ticket.

For issues with AWS ParallelCluster >= v2.9.0 and scheduler == slurm, please attach the following logs:
* From Head node: `/var/log/parallelcluster/clustermgtd.log`, `/var/log/parallelcluster/slurm_resume.log`, `/var/log/parallelcluster/slurm_suspend.log`, and `/var/log/slurmctld.log`
* From Compute node:  `/var/log/parallelcluster/computemgtd.log`, and `/var/log/slurmd.log`

Otherwise, please attach the following logs:
* From Head node: `/var/log/jobwatcher`, `/var/log/sqswatcher`, and `/var/log/slurmctld.log` if scheduler == slurm.
* From Compute node:`/var/log/nodewatcher`, and `/var/log/slurmd.log` if scheduler == slurm

**If you are reporting issues about cluster creation failure or node failure:**

If the cluster fails creation, please re-execute `create` action using `--norollback` option.

We cannot work on issues without proper logs. We **STRONGLY** recommend following [this guide](https://github.com/aws/aws-parallelcluster/wiki/Creating-an-Archive-of-a-Cluster's-Logs) and attach the complete cluster log archive with the ticket.

* From Head node: `/var/log/cloud-init.log`, `/var/log/cfn-init.log`, and `/var/log/chef-client.log`
* From Compute node:  `/var/log/cloud-init-output.log`

**Additional context:**
Any other context about the problem. E.g.:
 - pre/post-install scripts, if any
 - screenshots, if useful
