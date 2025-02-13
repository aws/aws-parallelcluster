---
name: Bug report for ParallelCluster 2.x.x
about: Detailed report for issues with ParallelCluster 2.x.x
title: ''
labels: 2.x
assignees: ''

---

If you have an active AWS support contract, please open a case with AWS Premium Support team using the below documentation to report the issue:
https://docs.aws.amazon.com/awssupport/latest/user/case-management.html

Before submitting a new issue, please search through [GitHub Issues](https://github.com/aws/aws-parallelcluster/issues?q=is%3Aissue), 
[GitHub Wiki](https://github.com/aws/aws-parallelcluster/wiki) and check out the [troubleshooting documentation](https://docs.aws.amazon.com/parallelcluster/latest/ug/troubleshooting.html).

Please make sure to add the following data in order to facilitate the root cause detection.

**Required Info:**
 - AWS ParallelCluster version [e.g. 2.11.0]:
 - Full cluster configuration without any credentials or personal data.
 - Cluster name:
 - [Optional] Arn of the cluster CloudFormation main stack:

**Bug description and how to reproduce:**
A clear and concise description of what the bug is and the steps to reproduce the behavior.

**If you are reporting issues about scaling or job failure:**
We cannot work on issues without proper logs. We **STRONGLY** recommend following [this guide](https://docs.aws.amazon.com/parallelcluster/latest/ug/troubleshooting.html#retrieving-and-preserve-logs) and attach the complete cluster log archive with the ticket.

For issues with AWS ParallelCluster >= v2.9.0 and scheduler == slurm, please attach the following logs:
* From Head node: `/var/log/parallelcluster/clustermgtd`, `/var/log/parallelcluster/slurm_resume.log`, `/var/log/parallelcluster/slurm_suspend.log` and`/var/log/slurmctld.log` 
* From Compute node:  `/var/log/parallelcluster/computemgtd.log` and `/var/log/slurmd.log`

Otherwise, please attach the following logs:
* From Head node: `/var/log/jobwatcher`, `/var/log/sqswatcher` and `/var/log/slurmctld.log` if scheduler == slurm.
* From Compute node:`/var/log/nodewatcher` and `/var/log/slurmd.log` if scheduler == slurm

**If you are reporting issues about cluster creation failure or node failure:**

If the cluster fails creation, please re-execute `create` action using `--norollback` option.

We cannot work on issues without proper logs. We **STRONGLY** recommend following [this guide](https://docs.aws.amazon.com/parallelcluster/latest/ug/troubleshooting.html#retrieving-and-preserve-logs) and attach the complete cluster log archive with the ticket.

Please be sure to attach the following logs: 
* From Head node: `/var/log/cloud-init.log`, `/var/log/cfn-init.log` and `/var/log/chef-client.log`
* From Compute node:  `/var/log/cloud-init-output.log`

**Additional context:**
Any other context about the problem. E.g.:
 - CLI logs: `~/.parallelcluster/pcluster-cli.log`
 - Custom bootstrap scripts, if any
 - Screenshots, if useful.
