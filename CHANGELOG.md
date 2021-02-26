CHANGELOG
=========

2.10.1
------

**ENHANCEMENTS**

- Add support for me-south-1 region (Bahrein), af-south-1 region (Cape Town) and eu-south-1 region (Milan)
  - At the time of this version launch:
    - Amazon FSx for Lustre and ARM instance types are not supported in me-south-1, af-south-1 and eu-south-1
    - AWS Batch is not supported in af-south-1
    - EBS io2 is not supported in af-south-1 and eu-south-1
- Install Arm Performance Libraries (APL) 20.2.1 on ARM AMIs (CentOS8, Alinux2, Ubuntu1804).
- Install EFA kernel module on ARM instances with `alinux2` and `ubuntu1804`. This enables support for `c6gn` instances.
- Add support for io2 and gp3 EBS volume type.
- Add `iam_lambda_role` parameter under `cluster` section to enable the possibility to specify an existing IAM role to 
  be used by AWS Lambda functions in CloudFormation. 
  When using `sge`, `torque`, or `slurm` as the scheduler, 
  `pcluster` will not create any IAM role if both `ec2_iam_role` and `iam_lambda_role` are provided.
- Improve robustness of a Slurm cluster when clustermgtd is down.
- Configure NFS threads to be max(8, num_cores) for performance. This enhancement will not take effect on Ubuntu 16.04.
- Optimize calls to DescribeInstanceTypes EC2 API when validating cluster configuration. 

**CHANGES**

- Upgrade EFA installer to version 1.11.1.
  - EFA configuration: ``efa-config-1.7`` (from efa-config-1.5)
  - EFA profile: ``efa-profile-1.3`` (from efa-profile-1.1)
  - EFA kernel module: ``efa-1.10.2`` (no change)
  - RDMA core: ``rdma-core-31.2amzn`` (from rdma-core-31.amzn0)
  - Libfabric: ``libfabric-1.11.1amzn1.0`` (from libfabric-1.11.1amzn1.1)
  - Open MPI: ``openmpi40-aws-4.1.0`` (from openmpi40-aws-4.0.5)
- Upgrade Intel MPI to version U8.
- Upgrade NICE DCV to version 2020.2-9662.
- Set default systemd runlevel to multi-user.target on all OSes during ParallelCluster official AMI creation.
  The runlevel is set to graphical.target on head node only when DCV is enabled. This prevents the execution of
  graphical services, such as x/gdm, when they are not required.
- Download Intel MPI and HPC packages from S3 rather than Intel yum repos.
- Change the default of instance types from the hardcoded `t2.micro` to the free tier instance type 
    (`t2.micro` or `t3.micro` dependent on region). In regions without free tier, the default is `t3.micro`.
- Enable support for p4d as head node instance type (p4d was already supported as compute node in 2.10.0).
- Pull Amazon Linux Docker images from public ECR when building docker image for `awsbatch` scheduler.
- Increase max retry attempts when registering Slurm nodes in Route53.

**BUG FIXES**

- Fix pcluster createami for Ubuntu 1804 by downloading SGE sources from Debian repository and not from the EOL
  Ubuntu 19.10.
- Remove CloudFormation DescribeStacks API call from AWS Batch Docker entrypoint. This removes the risk of job
  failures due to CloudFormation throttling.
- Mandate the presence of `vpc_settings`, `vpc_id`, `master_subnet_id` in the config file to avoid unhandled exceptions.
- Set the default EBS volume size to 500 GiB when volume type is `st1` or `sc1`.
- Fix installation of Intel PSXE package on CentOS 7 by using yum4.
- Fix routing issues with multiple Network Interfaces on Ubuntu 18.04.
  
2.10.0
------

**ENHANCEMENTS**

- Add support for CentOS 8 in all Commercial regions.
- Add support for P4d instance type as compute node.
- Add the possibility to enable NVIDIA GPUDirect RDMA support on EFA by using the new `enable_efa_gdr` configuration
  parameter.
- Enable support for NICE DCV in GovCloud regions.
- Enable support for AWS Batch scheduler in GovCloud regions.
- FSx Lustre:
  - Add possibility to configure Auto Import policy through the new `auto_import_policy` parameter.
  - Add support to HDD storage type and the new `storage_type` and `drive_cache_type` configuration parameters.
- Create a CloudWatch Dashboard for the cluster, named `<clustername>-<region>`, including head node EC2 metrics and 
  cluster logs. It can be disabled by configuring the `enable` parameter in the `dashboard` section.
- Add `-r/-region` arg to `pcluster configure` command. If this arg is provided, configuration will 
  skip region selection.
- Add `-r/-region` arg to`ssh` and `dcv connect` commands.
- Add `cluster_resource_bucket` parameter under `cluster` section to allow the user to specify an existing S3 bucket.
- `createami`:
  - Add validation step to fail when using a base AMI created by a different version of ParallelCluster.
  - Add validation step for AMI creation process to fail if the selected OS and the base AMI OS are not consistent.
  - Add `--post-install` parameter to use a post installation script when building an AMI.
  - Add the possibility to use a ParallelCluster base AMI.
- Add possibility to change tags when performing a `pcluster update`.
- Add new `all_or_nothing_batch` configuration parameter for `slurm_resume` script. When `True`, `slurm_resume` will
  succeed only if all the instances required by all the pending jobs in Slurm will be available.
- Enable queue resizing on update without requiring to stop the compute fleet. Stopping the compute fleet is only
  necessary when existing instances risk to be terminated.
- Add validator for EBS volume size, type and IOPS.
- Add validators for `shared_dir` parameter when used in both `cluster` and `ebs` sections.
- Add validator `cfn_scheduler_slots` key in the `extra_json` parameter.


**CHANGES**

- CentOS 6 is no longer supported.
- Upgrade EFA installer to version 1.10.1
  - EFA configuration: `efa-config-1.5` (from efa-config-1.4)
  - EFA profile: `efa-profile-1.1` (from efa-profile-1.0.0)
  - EFA kernel module: `efa-1.10.2` (from efa-1.6.0)
  - RDMA core: `rdma-core-31.amzn0` (from rdma-core-28.amzn0)
  - Libfabric: `libfabric-1.11.1amzn1.1` (from libfabric-1.10.1amzn1.1)
  - Open MPI: `openmpi40-aws-4.0.5` (from openmpi40-aws-4.0.3)
  - Unifies installer runtime options across x86 and aarch64
  - Introduces `-g/--enable-gdr` switch to install packages with GPUDirect RDMA support
  - Updates to OMPI collectives decision file packaging, migrated from efa-config to efa-profile
  - Introduces CentOS 8 support
- Upgrade NVIDIA driver to version 450.80.02.
- Install NVIDIA Fabric manager to enable NVIDIA NVSwitch on supported platforms.
- Remove default region `us-east-1`. After the change, `pcluster` will adhere to the following lookup order for region:
  1. `-r/--region` arg.
  2. `AWS_DEFAULT_REGION` environment variable.
  3. `aws_region_name` in ParallelCluster configuration file.
  4. `region` in AWScli configuration file.
- Slurm: change `SlurmctldPort` to 6820-6829 to not overlap with default `slurmdbd` port (6819).
- Slurm: add `compute_resource` name and `efa` as node features.
- Remove validation on `ec2_iam_role` parameter.
- Improve retrieval of instance type info by using `DescribeInstanceType` API.
- Remove `custom_awsbatch_template_url` configuration parameter.
- Upgrade `pip` to latest version in virtual environments.
- Upgrade image used by CodeBuild environment when building container images for Batch clusters, from
  `aws/codebuild/amazonlinux2-x86_64-standard:1.0` to `aws/codebuild/amazonlinux2-x86_64-standard:3.0`.

**BUG FIXES**

- Retrieve the right number of compute instance slots when instance type is updated.
- Include user tags in compute nodes and EBS volumes.
- Fix `pcluster status` output when head node is stopped.
- `pcluster update`:
  - Fix issue when tags are specified but not changed.
  - Fix issue when the `cluster` section label changed.
  - Fix issue when `shared_dir` and `ebs_settings` are both configured in the `cluster` section.
  - Fix `cluster` and `cfncluster` compatibility in `extra_json` parameter.
- Fix `pcluster configure` to avoid using default/initial values for internal parameter initialization.
- Fix pre/post install script arguments management when using double quotes.
- Fix a bug that was causing `clustermgtd` and `computemgtd` sleep interval to be incorrectly computed when
  system timezone is not set to UTC.
- Fix queue name validator to properly check for capital letters.
- Fix `enable_efa` parameter validation for `queue` section.
- Fix CloudWatch Log Group creation for AWS Lambda functions handling CloudFormation Custom Resources.

2.9.1
-----

**BUG FIXES**

- Fix cluster creation with the head node in a private subnet when it doesn't get a public IP.

2.9.0
-----

**ENHANCEMENTS**

- Add support for multiple queues and multiple instance types feature with the Slurm scheduler.
- Extend NICE DCV support to ARM instances.
- Extend support to disable hyperthreading on instances (like \*.metal) that don't support CpuOptions in
  LaunchTemplate.
- Enable support for NFS 4 for the filesystems shared from the head node.
- Add CLI utility to convert configuration files with Slurm scheduler to new format to support multiple queues
  configuration.
- Add script wrapper to support Torque-like commands with the Slurm scheduler.
- Remove dependency on cfn-init in compute nodes bootstrap in order to avoid throttling and delays caused by CloudFormation when a large number of compute nodes join the cluster.

**CHANGES**

- Introduce new configuration sections and parameters to support multiple queues and multiple instance types.
- Optimize scaling logic with Slurm scheduler, no longer based on Auto Scaling groups.
- A Route53 private hosted zone is now created together with the cluster and used in DNS resolution inside cluster nodes
  when using Slurm scheduler.
- Upgrade EFA installer to version 1.9.5:
  - EFA configuration: ``efa-config-1.4`` (from efa-config-1.3)
  - EFA profile: ``efa-profile-1.0.0``
  - EFA kernel module: ``efa-1.6.0`` (no change)
  - RDMA core: ``rdma-core-28.amzn0`` (no change)
  - Libfabric: ``libfabric-1.10.1amzn1.1`` (no change)
  - Open MPI: ``openmpi40-aws-4.0.3`` (no change)
- Upgrade Slurm to version 20.02.4.
- Upgrade NICE DCV to version 2020.1-9012.
- Use private IP instead of master node hostname when mounting shared NFS drives.
- Add new log streams to CloudWatch: chef-client, clustermgtd, computemgtd, slurm_resume, slurm_suspend.
- Add support for queue names in pre/post install scripts.
- Use PAY_PER_REQUEST billing mode for DynamoDb table in govcloud regions.
- Add limit of section names length to 30 characters in the configuration file.

**BUG FIXES**

- Solve dpkg lock issue with Ubuntu that prevented custom AMI creation in some cases.
- Add/improve sanity checks for some configuration parameters.
- Prevent ignored changes from being reported in ``pcluster update`` output.
- Fix incompatibility issues with python 2.7 for ``pcluster update``.
- Fix SNS Topic Subscriptions not being deleted with cluster's CloudFormation stack.

2.8.1
-----

**CHANGES**

- Disable screen lock for DCV desktop sessions to prevent users from being locked out.

**BUG FIXES**

- Fix ``pcluster configure`` command to avoid writing unexpected configuration parameters.

2.8.0
-----

**ENHANCEMENTS**

- Enable support for ARM instances on Ubuntu 18.04 and Amazon Linux 2.
- Add support for the automatic backup features of FSx file systems.
- Renewed user experience and robustness of cluster update functionality.
- Support DCV and EFS in China regions.
- Use DescribeInstanceTypes API to validate whether an instance type is EFA-enabled so that new EFA instances can
  be used without requiring an update to the ParallelCluster configuration files.
- Enable Slurm to directly launch tasks and initialize communications through PMIx v3.1.5 on all supported
  operating systems except for CentOS 6.
- Print a warning when using NICE DCV on micro or nano instances.

**CHANGES**

- Remove the client requirement to have Berkshelf to build a custom AMI.
- Upgrade EFA installer to version 1.9.4:
  - Kernel module: ``efa-2.6.0`` (from efa-1.5.1)
  - RDMA core: ``rdma-core-28.amzn0`` (from rdma-core-25.0)
  - Libfabric: ``libfabric-1.10.1amzn1.1`` (updated from libfabric-aws-1.9.0amzn1.1) 
  - Open MPI: openmpi40-aws-4.0.3 (no change)
- Avoid unnecessary validation of IAM policies.
- Removed unused dependency on supervisor from the Batch Dockerfile.
- Move all LogGroup definitions in the CloudFormation templates into the CloudWatch substack.
- Disable libvirtd service on CentOS 7. Virtual bridge interfaces are incorrectly detected by Open MPI and
  cause MPI applications to hang, see https://www.open-mpi.org/faq/?category=tcp#tcp-selection for details 
- Use CINC instead of Chef for provisioning instances. See https://cinc.sh/about/ for details.
- Retry when mounting an NFS mount fails.
- Install the ``pyenv`` virtual environments used by ParallelCluster cookbook and node daemon code under
  /opt/parallelcluster instead of under /usr/local.
- Use the new official CentOS 7 AMI as the base images for ParallelCluster AMI.
- Upgrade NVIDIA driver to Tesla version 440.95.01 on CentOS 6 and version 450.51.05 on all other distros.
- Upgrade CUDA library to version 11.0 on all distros besides CentOS 6.
- Install third-party cookbook dependencies via local source, rather than using the Chef supermarket.
- Use https wherever possible in download URLs.
- Install glibc-static, which is required to support certain options for the Intel MPI compiler.
- Require an initial cluster size greater than zero when the option to maintain the initial cluster size is used.

**BUG FIXES**

- Fix validator for CIDR-formatted IP range parameters.
- Fix issue that was preventing concurrent use of custom node and pcluster CLI packages.
- Use the correct domain name when contacting AWS services from the China partition.

2.7.0
-----

**ENHANCEMENTS**

- ``sqswatcher``: The daemon is now compatible with VPC Endpoints so that SQS messages can be passed without traversing
  the public internet.

**CHANGES**

- Upgrade NICE DCV to version 2020.0-8428.
- Upgrade Intel MPI to version U7.
- Upgrade NVIDIA driver to version 440.64.00.
- Upgrade EFA installer to version 1.8.4:
  - Kernel module: ``efa-1.5.1`` (no change)
  - RDMA core: ``rdma-core-25.0`` (no change)
  - Libfabric: ``libfabric-aws-1.9.0amzn1.1`` (no change)
  - Open MPI: openmpi40-aws-4.0.3 (updated from openmpi40-aws-4.0.2)
- Upgrade CentOS 7 AMI to version 7.8
- Configuration: base_os and scheduler parameters are now mandatory and they have no longer a default value.

**BUG FIXES**

- Fix recipes installation at runtime by adding the bootstrapped file at the end of the last chef run.
- Fix installation of FSx Lustre client on Centos 7
- FSx Lustre: Exit with error when failing to retrieve FSx mountpoint
- Fix sanity_check behavior when ``max queue_size`` > 1000

2.6.1
-----

**ENHANCEMENTS**

- Improved management of S3 bucket that gets created when ``awsbatch`` scheduler is selected.
- Add validation for supported OSes when using FSx Lustre.
- Change ProctrackType from proctrack/gpid to proctrack/cgroup in Slurm in order to better handle termination of
  stray processes when running MPI applications. This also includes the creation of a cgroup Slurm configuration in
  in order to enable the cgroup plugin.
- Skip execution, at node bootstrap time, of all those install recipes that are already applied at AMI creation time.
- Start CloudWatch agent earlier in the node bootstrapping phase so that cookbook execution failures are correctly
  uploaded and are available for troubleshooting.
- Improved the management of SQS messages and retries to speed-up recovery times when failures occur.

**CHANGES**

- FSx Lustre: remove ``x-systemd.requires=lnet.service`` from mount options in order to rely on default lnet setup
  provided by Lustre.
- Enforce Packer version to be >= 1.4.0 when building an AMI. This is also required for customers using ``pcluster
  createami`` command.
- Do not launch a replacement for an unhealthy or unresponsive node until this is terminated. This makes cluster slower
  at provisioning new nodes when failures occur but prevents any temporary over-scaling with respect to the expected
  capacity.
- Increase parallelism when starting ``slurmd`` on compute nodes that join the cluster from 10 to 30.
- Reduce the verbosity of messages logged by the node daemons.
- Do not dump logs to ``/home/logs`` when nodewatcher encounters a failure and terminates the node. CloudWatch can be
  used to debug such failures.
- Reduce the number of retries for failed REMOVE events in sqswatcher.
- Omit cfn-init-cmd and cfn-wire from the files stored in CloudWatch logs.

**BUG FIXES**

- Configure proxy during cloud-init boothook in order for the proxy to be configured for all bootstrap actions.
- Fix installation of Intel Parallel Studio XE Runtime that requires yum4 since version 2019.5.
- Fix compilation of Torque scheduler on Ubuntu 18.04.
- Fixed a bug in the ordering and retrying of SQS messages that was causing, under certain circumstances of heavy load,
  the scheduler configuration to be left in an inconsistent state.
- Delete from queue the REMOVE events that are discarded due to hostname collision with another event fetched as part
  of the same ``sqswatcher`` iteration.


2.6.0
-----

**ENHANCEMENTS**

- Add support for Amazon Linux 2
- Add support for NICE DCV on Ubuntu 18.04
- Add support for FSx Lustre on Ubuntu 18.04 and Ubuntu 16.04
- New CloudWatch logging capability to collect cluster and job scheduler logs to CloudWatch for cluster monitoring and inspection
  - Add ``--keep-logs`` flag to ``pcluster delete`` command to preserve logs at cluster deletion
- Install and setup Amazon Time Sync on all OSs
- Enabling accounting plugin in Slurm for all OSes. Note: accounting is not enabled nor configured by default
- Add retry on throttling from CloudFormation API, happening when several compute nodes are being bootstrapped
  concurrently
- Display detailed substack failures when ``pcluster create`` fails due to a substack error
- Create additional EFS mount target in the AZ of compute subnet, if needed
- Add validator for FSx Lustre Weekly Maintenance Start Time parameter
- Add validator to the KMS key provided for EBS, FSx, and EFS
- Add validator for S3 external resource
- Support two new FSx Lustre features, Scratch 2 and Persistent filesystems
  - Add two new parameters ``deployment_type`` and ``per_unit_storage_throughput`` to the ``fsx`` section
  - Add new storage sizes ``storage_capacity``, 1,200 GiB, 2,400 GiB and multiples of 2,400 are supported with ``SCRATCH_2``
  - In transit encryption is available via ``fsx_kms_key_id`` parameter when ``deployment_type = PERSISTENT_1``
  - New parameter ``per_unit_storage_throughput`` is available when ``deployment_type = PERSISTENT_1``


**CHANGES**

- Upgrade Slurm to version 19.05.5
- Upgrade Intel MPI to version U6
- Upgrade EFA installer to version 1.8.3:
  - Kernel module: efa-1.5.1 (updated from efa-1.4.1)
  - RDMA core: rdma-core-25.0 (distributed only) (no change)
  - Libfabric: libfabric-aws-1.9.0amzn1.1 (updated from libfabric-aws-1.8.1amzn1.3)
  - Open MPI: openmpi40-aws-4.0.2 (no change)
- Install Python 2.7.17 on CentOS 6 and set it as default through pyenv
- Install Ganglia from repository on Amazon Linux, Amazon Linux 2, CentOS 6 and CentOS 7
- Disable StrictHostKeyChecking for SSH client when target host is inside cluster VPC for all OSs except CentOS 6
- Pin Intel Python 2 and Intel Python 3 to version 2019.4
- Automatically disable ptrace protection on Ubuntu 18.04 and Ubuntu 16.04 compute nodes when EFA is enabled.
  This is required in order to use local memory for interprocess communications in Libfabric provider
  as mentioned here: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start.html#efa-start-ptrace
- Packer version >= 1.4.0 is required for AMI creation
- Use version 5.2 of PyYAML for python 3 versions of 3.4 or earlier.

**BUG FIXES**

- Fix issue with slurmd daemon not being restarted correctly when a compute node is rebooted
- Fix errors causing Torque not able to locate jobs, setting server_name to fqdn on master node
- Fix Torque issue that was limiting the max number of running jobs to the max size of the cluster
- Fix OS validation depending on the configured scheduler

2.5.1
-----

**ENHANCEMENTS**

- Add ``--show-url`` flag to ``pcluster dcv connect`` command in order to generate a one-time URL that can be used to
  start a DCV session. This unblocks the usage of DCV when the browser cannot be launched automatically.

**CHANGES**

- Upgrade NVIDIA driver to Tesla version 440.33.01.
- Upgrade CUDA library to version 10.2.
- Using a Placement Group is not required anymore but highly recommended when enabling EFA.
- Increase default root volume size in Centos 6 AMI to 25GB.
- Increase the retention of CloudWatch logs produced when generating AWS Batch Docker images from 1 to 14 days.
- Increase the total time allowed to build Docker images from 20 minutes to 30 minutes. This is done to better deal
  with slow networking in China regions.
- Upgrade EFA installer to version 1.7.1:
  - Kernel module: ``efa-1.4.1``
  - RDMA core: ``rdma-core-25.0``
  - Libfabric: ``libfabric-aws-1.8.1amzn1.3``
  - Open MPI: ``openmpi40-aws-4.0.2``

**BUG FIXES**

- Fix installation of NVIDIA drivers on Ubuntu 18.
- Fix installation of CUDA toolkit on Centos 6.
- Fix invalid default value for ``spot_price``.
- Fix issue that was preventing the cluster from being created in VPCs configured with multiple CIDR blocks.
- Correctly handle failures when retrieving ASG in ``pcluster instances`` command.
- Fix the default mount dir when a single EBS volume is specified through a dedicated ebs configuration section.
- Correctly handle failures when there is an invalid parameter in the ``aws`` config section.
- Fix a bug in ``pcluster delete`` that was causing the cli to exit with error when the cluster is successfully deleted.
- Exit with status code 1 if ``pcluster create`` fails to create a stack.
- Better handle the case of multiple or no network interfaces on FSX filesystems.
- Fix ``pcluster configure`` to retain default values from old config file.
- Fix bug in sqswatcher that was causing the daemon to fail when more than 100 DynamoDB tables are present in the
  cluster region.
- Fix installation of Munge on Amazon Linux, Centos 6, Centos 7 and Ubuntu 16.


2.5.0
-----

**ENHANCEMENTS**

- Add support for new OS: Ubuntu 18.04
- Add support for AWS Batch scheduler in China partition and in ``eu-north-1``.
- Revamped ``pcluster configure`` command which now supports automated networking configuration.
- Add support for NICE DCV on Centos 7 to setup a graphical remote desktop session on the Master node.
- Add support for new EFA supported instances: ``c5n.metal``, ``m5dn.24xlarge``, ``m5n.24xlarge``, ``r5dn.24xlarge``,
  ``r5n.24xlarge``
- Add support for scheduling with GPU options in Slurm. Currently supports the following GPU-related options: ``—G/——gpus,
  ——gpus-per-task, ——gpus-per-node, ——gres=gpu, ——cpus-per-gpu``.
  Integrated GPU requirements into scaling logic, cluster will scale automatically to satisfy GPU/CPU requirements
  for pending jobs. When submitting GPU jobs, CPU/node/task information is not required but preferred in order to
  avoid ambiguity. If only GPU requirements are specified, cluster will scale up to the minimum number of nodes
  required to satisfy all GPU requirements.
- Add new cluster configuration option to automatically disable Hyperthreading (``disable_hyperthreading = true``)
- Install Intel Parallel Studio 2019.5 Runtime in Centos 7 when ``enable_intel_hpc_platform = true``  and share /opt/intel over NFS
- Additional EC2 IAM Policies can now be added to the role ParallelCluster automatically creates for cluster nodes by
  simply specifying ``additional_iam_policies`` in the cluster config.

**CHANGES**

- Ubuntu 14.04 is no longer supported
- Upgrade Intel MPI to version U5.
- Upgrade EFA Installer to version 1.7.0, this also upgrades Open MPI to 4.0.2.
- Upgrade NVIDIA driver to Tesla version 418.87.
- Upgrade CUDA library to version 10.1.
- Upgrade Slurm to version 19.05.3-2.
- Install EFA in China AMIs.
- Increase default EBS volume size from 17GB to 25GB
- FSx Lustre now supports new storage_capacity options 1,200 and 2,400 GiB
- Enable ``flock user_xattr noatime`` Lustre mount options by default everywhere and
  ``x-systemd.automount x-systemd.requires=lnet.service`` for systemd based systems.
- Increase the number of hosts that can be processed by scaling daemons in a single batch from 50 to 200. This
  improves the scaling time especially with increased ASG launch rates.
- Change default sshd config in order to disable X11 forwarding and update the list of supported ciphers.
- Increase faulty node termination timeout from 1 minute to 5 in order to give some additional time to the scheduler
  to recover when under heavy load.
- Extended ``pcluster createami`` command to specify the VPC and network settings when building the AMI.
- Support inline comments in config file
- Support Python 3.8 in pcluster CLI.
- Deprecate Python 2.6 support
- Add ``ClusterName`` tag to EC2 instances.
- Search for new available version only at ``pcluster create`` action.
- Enable ``sanity_check`` by default.

**BUG FIXES**

- Fix sanity check for custom ec2 role. Fixes [#1241](https://github.com/aws/aws-parallelcluster/issues/1241).
- Fix bug when using same subnet for both master and compute.
- Fix bug when ganglia is enabled ganglia urls are shown. Fixes [#1322](https://github.com/aws/aws-parallelcluster/issues/1322).
- Fix bug with ``awsbatch`` scheduler that prevented Multi-node jobs from running.
- Fix jobwatcher behaviour that was marking nodes locked by the nodewatcher as busy even if they had been removed
  already from the ASG Desired count. This was causing, in rare circumstances, a cluster overscaling.
- Fix bug that was causing failures in sqswatcher when ADD and REMOVE event for the same host are fetched together.
- Fix bug that was preventing nodes to mount partitioned EBS volumes.
- Implement paginated calls in ``pcluster list``.
- Fix bug when creating ``awsbatch`` cluster with name longer than 31 chars
- Fix a bug that lead to ssh not working after ssh'ing into a compute node by ip address.

2.4.1
-----

**ENHANCEMENTS**

- Add support for ap-east-1 region (Hong Kong)
- Add possibility to specify instance type to use when building custom AMIs with ``pcluster createami``
- Speed up cluster creation by having compute nodes starting together with master node. **Note** this requires one new IAM permissions in the [ParallelClusterInstancePolicy](https://docs.aws.amazon.com/en_us/parallelcluster/latest/ug/iam.html#parallelclusterinstancepolicy), ``cloudformation:DescribeStackResource``
- Enable ASG CloudWatch metrics for the ASG managing compute nodes. **Note** this requires two new IAM permissions in the [ParallelClusterUserPolicy](https://docs.aws.amazon.com/parallelcluster/latest/ug/iam.html#parallelclusteruserpolicy), ``autoscaling:DisableMetricsCollection`` and ``autoscaling:EnableMetricsCollection``
- Install Intel MPI 2019u4 on Amazon Linux, Centos 7 and Ubuntu 1604
- Upgrade Elastic Fabric Adapter (EFA) to version 1.4.1 that supports Intel MPI
- Run all node daemons and cookbook recipes in isolated Python virtualenvs. This allows our code to always run with the
  required Python dependencies and solves all conflicts and runtime failures that were being caused by user packages
  installed in the system Python
- Torque:
  - Process nodes added to or removed from the cluster in batches in order to speed up cluster scaling
  - Scale up only if required CPU/nodes can be satisfied
  - Scale down if pending jobs have unsatisfiable CPU/nodes requirements
  - Add support for jobs in hold/suspended state (this includes job dependencies)
  - Automatically terminate and replace faulty or unresponsive compute nodes
  - Add retries in case of failures when adding or removing nodes
  - Add support for ncpus reservation and multi nodes resource allocation (e.g. -l nodes=2:ppn=3+3:ppn=6)
  - Optimized Torque global configuration to faster react to the dynamic cluster scaling

**CHANGES**

- Update EFA installer to a new version, note this changes the location of ``mpicc`` and ``mpirun``.
  To avoid breaking existing code, we recommend you use the modulefile ``module load openmpi`` and ``which mpicc``
  for anything that requires the full path
- Eliminate Launch Configuration and use Launch Templates in all the regions
- Torque: upgrade to version 6.1.2
- Run all ParallelCluster daemons with Python 3.6 in a virtualenv. Daemons code now supports Python >= 3.5

**BUG FIXES**

- Fix issue with sanity check at creation time that was preventing clusters from being created in private subnets
- Fix pcluster configure when relative config path is used
- Make FSx Substack depend on ComputeSecurityGroupIngress to keep FSx from trying to create prior to the SG
  allowing traffic within itself
- Restore correct value for ``filehandle_limit`` that was getting reset when setting ``memory_limit`` for EFA
- Torque: fix compute nodes locking mechanism to prevent job scheduling on nodes being terminated
- Restore logic that was automatically adding compute nodes identity to SSH ``known_hosts`` file
- Slurm: fix issue that was causing the ParallelCluster daemons to fail when the cluster is stopped and an empty compute nodes file
  is imported in Slurm config


2.4.0
-----

**ENHANCEMENTS**

- Add support for EFA on Centos 7, Amazon Linux and Ubuntu 1604
- Add support for Ubuntu in China region ``cn-northwest-1``
- SGE:
  - process nodes added to or removed from the cluster in batches in order to speed up cluster scaling.
  - scale up only if required slots/nodes can be satisfied
  - scale down if pending jobs have unsatisfiable CPU/nodes requirements
  - add support for jobs in hold/suspended state (this includes job dependencies)
  - automatically terminate and replace faulty or unresponsive compute nodes
  - add retries in case of failures when adding or removing nodes
  - configure scheduler to handle rescheduling and cancellation of jobs running on failing or terminated nodes
- Slurm:
  - scale up only if required slots/nodes can be satisfied
  - scale down if pending jobs have unsatisfiable CPU/nodes requirements
  - automatically terminate and replace faulty or unresponsive compute nodes
  - decrease SlurmdTimeout to 120 seconds to speed up replacement of faulty nodes
- Automatically replace compute instances that fail initialization and dump logs to shared home directory.
- Dynamically fetch compute instance type and cluster size in order to support updates in scaling daemons
- Always use full master FQDN when mounting NFS on compute nodes. This solves some issues occurring with some networking
  setups and custom DNS configurations
- List the version and status during ``pcluster list``
- Remove double quoting of the post_install args
- ``awsbsub``: use override option to set the number of nodes rather than creating multiple JobDefinitions
- Add support for AWS_PCLUSTER_CONFIG_FILE env variable to specify pcluster config file

**CHANGES**

- Update openmpi library to version 3.1.4 on Centos 7, Amazon Linux and Ubuntu 1604. This also changes the default
  openmpi path to ``/opt/amazon/efa/bin/`` and the openmpi module name to ``openmpi/3.1.4``
- Set soft and hard ulimit on open files to 10000 for all supported OSs
- For a better security posture, we're removing AWS credentials from the ``parallelcluster`` config file
  Credentials can be now setup following the canonical procedure used for the aws cli
- When using FSx or EFS do not enforce in sanity check that the compute security group is open to 0.0.0.0/0
- When updating an existing cluster, the same template version is now used, no matter the pcluster cli version
- SQS messages that fail to be processed in ``sqswatcher`` are now re-queued only 3 times and not forever
- Reset ``nodewatcher`` idletime to 0 when the host becomes essential for the cluster (because of min size of ASG or
  because there are pending jobs in the scheduler queue)
- SGE: a node is considered as busy when in one of the following states "u", "C", "s", "d", "D", "E", "P", "o".
  This allows a quick replacement of the node without waiting for the ``nodewatcher`` to terminate it.
- Do not update DynamoDB table on cluster updates in order to avoid hitting strict API limits (1 update per day).

**BUG FIXES**

- Fix issue that was preventing Torque from being used on Centos 7
- Start node daemons at the end of instance initialization. The time spent for post-install script and node
  initialization is not counted as part of node idletime anymore.
- Fix issue which was causing an additional and invalid EBS mount point to be added in case of multiple EBS
- Install Slurm libpmpi/libpmpi2 that is distributed in a separate package since Slurm 17
- ``pcluster ssh`` command now works for clusters with ``use_public_ips = false``
- Slurm: add "BeginTime", "NodeDown", "Priority" and "ReqNodeNotAvail" to the pending reasons that trigger
  a cluster scaling
- Add a timeout on remote commands execution so that the daemons are not stuck if the compute node is unresponsive
- Fix an edge case that was causing the ``nodewatcher`` to hang forever in case the node had become essential to the
  cluster during a call to ``self_terminate``.
- Fix ``pcluster start/stop`` commands when used with an ``awsbatch`` cluster


2.3.1
-----

**ENHANCEMENTS**

- Add support for FSx Lustre with Amazon Linux. In case of custom AMI,
  The kernel will need to be ``>= 4.14.104-78.84.amzn1.x86_64``
- Slurm
   - set compute nodes to DRAIN state before removing them from cluster. This prevents the scheduler from submitting a job to a node that is being terminated.
   - dynamically adjust max cluster size based on ASG settings
   - dynamically change the number of configured FUTURE nodes based on the actual nodes that join the cluster. The max size of the cluster seen by the scheduler always matches the max capacity of the ASG.
   - process nodes added to or removed from the cluster in batches. This speeds up cluster scaling which is able to react with a delay of less than 1 minute to variations in the ASG capacity.
   - add support for job dependencies and pending reasons. The cluster won't scale up if the job cannot start due to an unsatisfied dependency.
   - set ``ReturnToService=1`` in scheduler config in order to recover instances that were initially marked as down due to a transient issue.
- Validate FSx parameters. Fixes [#896](https://github.com/aws/aws-parallelcluster/issues/896).

**CHANGES**

- Slurm - Upgrade version to 18.08.6.2
- NVIDIA - update drivers to version 418.56
- CUDA - update toolkit to version 10.0
- Increase default EBS volume size from 15GB to 17GB
- Disabled updates to FSx File Systems, updates to most parameters would cause the filesystem, and all it's data, to be deleted

**BUG FIXES**

- Cookbook wasn't fetched when ``custom_ami`` parameter specified in the config
- Cfn-init is now fetched from us-east-1, this bug effected non-alinux custom ami's in regions other than us-east-1.
- Account limit check not done for SPOT or AWS Batch Clusters
- Account limit check fall back to master subnet. Fixes [#910](https://github.com/aws/aws-parallelcluster/issues/910).
- Boto3 upperbound removed

2.2.1
-----

**ENHANCEMENTS**

- Add support for FSx Lustre in Centos 7. In case of custom AMI, FSx Lustre is
  only supported with Centos 7.5 and Centos 7.6.
- Check AWS EC2 instance account limits before starting cluster creation
- Allow users to force job deletion with ``SGE`` scheduler

**CHANGES**

- Set default value to ``compute`` for ``placement_group`` option
- ``pcluster ssh``: use private IP when the public one is not available
- ``pcluster ssh``: now works also when stack is not completed as long as the master IP is available
- Remove unused dependency on ``awscli`` from ParallelCluster package

**BUG FIXES**

- ``awsbsub``: fix file upload with absolute path
- ``pcluster ssh``: fix issue that was preventing the command from working correctly when stack status is
  ``UPDATE_ROLLBACK_COMPLETE``
- Fix block device conversion to correctly attach EBS nvme volumes
- Wait for Torque scheduler initialization before completing master node setup
- ``pcluster version``: now works also when no ParallelCluster config is present
- Improve ``nodewatcher`` daemon logic to detect if a SGE compute node has running jobs

**DOCS**

- Add documentation on how to use FSx Lustre
- Add tutorial for encrypted EBS with a Custom KMS Key
- Add ``ebs_kms_key_id`` to Configuration section

**TESTING**

- Define a new framework to write and run ParallelCluster integration tests
- Improve scaling integration tests to detect over-scaling
- Implement integration tests for awsbatch scheduler
- Implement integration tests for FSx Lustre file system

2.1.1
-----
- Add China regions ``cn-north-1`` and ``cn-northwest-1``

2.1.0
-----
- Add configuration for RAID 0 and 1 volumes
- Add Elastic File System (EFS) support
- Add AWS Batch Multinode Parallel jobs support
- Add support for Stockholm region (``eu-north-1``)
- Add ``--env``and ``--env-blacklist``options to the ``awsbsub`` command to export environment variables
  in the job environment
- Add ``--input-file``option to the ``awsbsub`` command to stage-in input files from the client
- Add new ``PCLUSTER_JOB_S3_URL`` variable to the job execution environment pointing to the S3 URL used
  for job data stage-in/out
- Add S3 URL for job data staging to the ``awsbstat -d``output
- Add ``--working-dir``and ``--parent-working-dir``options to the ``awsbsub`` command to specify
  the working-directory or the parent working directory for the job
- Add CPUs and Memory information to the ``awsbhosts -d``command

2.0.2
-----
- Add support for GovCloud East, us-gov-east-1 region
- Fix regression with ``shared_dir`` parameter in the cluster configuration section.
- bugfix:``cfncluster-cookbook``: Fix issue with jq on ubuntu1404 and centos6. Now using version 1.4.
- bugfix:``cfncluster-cookbook``: Fix dependency issue with AWS CLI package on ubuntu1404.

2.0.1
-----
- Fix ``configure`` and ``createami`` commands

2.0.0
-----
- Rename CfnCluster to AWS ParallelCluster
- Support multiple EBS Volumes
- Add AWS Batch as a supported scheduler
- Support Custom AMI's

1.6.1
-----
- Fix a bug in ``cfncluster configure``introduced in 1.6.0

1.6.0
-----
- Refactor scaling up to take into account the number of pending/requested jobs/slots and instance slots.
- Refactor scaling down to scale down faster and take advantage of per-second billing.
- Add ``scaledown_idletime`` parameter as part of scale-down refactoring
- Lock hosts before termination to ensure removal of dead compute nodes from host list
- Fix HTTP proxy support

1.5.4
-----
- Add option to disable ganglia ``extra_json = { "cfncluster" : { "ganglia_enabled" : "no" } }``
- Fix ``cfncluster update``bug
- Set SGE Accounting summary to be true, this reports a single accounting record for a mpi job
- Upgrade cfncluster-node to Boto3

1.5.3
-----
- Add support for GovCloud, us-gov-west-1 region

1.5.2
-----
- feature:``cfncluster``: Added ClusterUser as a stack output. This makes it easier to get the username of the head node.
- feature:``cfncluster``: Added ``cfncluster ssh cluster_name``, this allows you to easily ssh into your clusters.
  It allows arbitrary command execution and extra ssh flags to be provided after the command.
  See https://aws-parallelcluster.readthedocs.io/en/latest/commands.html#ssh
- change:``cfncluster``: Moved global cli flags to the command specific flags.
  For example ``cfncluster --region us-east-1 create``now becomes ``cfncluster create --region us-east-1``
- bugfix:``cfncluster-cookbook``: Fix bug that prevented c5d/m5d instances from working
- bugfix:``cfncluster-cookbook``: Set CPU as a consumable resource in slurm
- bugfix:``cfncluster-node``: Fixed Slurm behavior to add CPU slots so multiple jobs can be scheduled on a single node

1.5.1
-----
- change:``cfncluster``: Added "ec2:DescribeVolumes" permissions to
  CfnClusterInstancePolicy
- change:``cfncluster``: Removed YAML CloudFormation template, it can be
  generated by the https://github.com/awslabs/aws-cfn-template-flip tool
- updates:``cfncluster``: Add support for eu-west-3 region
- feature:``cfncluster-cookbook``: Added parameter to specify custom
  cfncluster-node package
- bugfix:``cfncluster``: Fix --template-url command line parameter
- bugfix:``cfncluster-cookbook``: Poll on EBS Volume attachment status
- bugfix:``cfncluster-cookbook``: Fixed SLURM cron job to publish pending metric
- bugfix:``cfncluster-node``: Fixed Torque behaviour when scaling up from an empty cluster


1.4.2
-----
- bugfix:``cfncluster``: Fix crash when base directory for config file
  does not exist
- bugfix:``cfncluster``: Removed extraneous logging message at
  cfncluster invocation, re-enabled logging in ~/.cfncluster/cfncluster-cli.log
- bugfix: ``cfncluster-node``: Fix scaling issues with CentOS 6 clusters caused
  by incompatible dependencies.
- updates:``ami``: Update all base AMIs to latest patch levels
- updates:``cfncluster-cookbook``: Updated to cfncluster-cookbook-1.4.1

1.4.1
-----
- bugfix:``cfncluster``: Fix abort due to undefinied logger

1.4.0
-----
- change:``cfncluster``: ``cfncluster stop``will terminate compute
  instances, but not stop the master node.
- feature:``cfncluster``: CfnCluster no longer maintains a whitelist
  of supported instance types, so new platforms are supported on day
  of launch (including C5).
- bugfix:``cfncluster-cookbook``: Support for NVMe instance store
- updates:``ami``: Update all base AMIs to latest patch levels
- bugfix:``cfncluster-node``: Fixed long scaling times with SLURM

1.3.2
-----
- feature:``cfncluster``: Add support for r2.xlarge/t2.2xlarge,
  x1.16xlarge, r4.*, f1.*, and i3.* instance types
- bugfix:``cfncluster``: Fix support for p2.2xlarge instance type
- feature:``cfncluster``: Add support for eu-west-2, us-east-2, and
  ca-central-1 regions
- updates:``cfncluster-cookbook``: Updated to cfncluster-cookbook-1.3.2
- updates:``ami``: Update all base AMIs to latest patch levels
- updates:``cfncluster``: Moved to Apache 2.0 license
- updates:``cfncluster``: Support for Python 3

1.3.1
-----
- feature:``ami``: Added support for Ubuntu 16.04 LTS
- feature:``ami``: Added NVIDIA 361.42 driver
- feature:``ami``: Added CUDA 7.5
- feature:``cfncluster``: Added support for tags in cluster section in the config
- feature:``cfncluster``: Added support for stopping/starting a cluster
- bugfix:``cfncluster``: Setting DYNAMIC for placement group sanity check fixed
- bugfix:``cfncluster``: Support any type of script for pre/post install
- updates:``cfncluster-cookbook``: Updated to cfncluster-cookbook-1.3.0
- updates:``cfncluster``: Updated docs with more detailed CLI help
- updates:``cfncluster``: Updated docs with development environment setup
- updates:``ami``: Updated to Openlava 3.3.3
- updates:``ami``: Updated to Slurm 16-05-3-1
- updates:``ami``: Updated to Chef 12.13.30
- updates:``ami``: Update all base AMIs to latest patch levels

1.2.1
-----
- bugfix:``cfncluster-node``: Use strings in command for sqswatcher on Python 2.6
- updates:``ami``: Update all base AMIs to latest patch levels

1.2.0
-----
- bugfix:``cfncluster-node``: Correctly set slots per host for Openlava
- updates:``cfncluster-cookbook``: Updated to cfncluster-cookbook-1.2.0
- updates:``ami``: Updated to SGE 8.1.9
- updates:``ami``: Updated to Openlava 3.1.3
- updates:``ami``: Updated to Chef 12.8.1

1.1.0
-----
- feature:``cfncluster``: Support for dynamic placement groups

1.0.1
-----
- bugfix:``cfncluster-node``: Fix for nodes being disabled when maintain_initial_size is true

1.0.0
------
Official release of the CfnCluster 1.x CLI, templates and AMIs. Available in all regions except BJS, with
support for Amazon Linux, CentOS 6 & 7 and Ubuntu 14.04 LTS. All AMIs are built via packer from the CfnCluster
Cookbook project (https://github.com/aws/aws-parallelcluster-cookbook).

1.0.0-beta
----------

This is a major update for CfnCluster. Boostrapping of the instances has moved from shell scripts into Chef
receipes. Through the use of Chef, there is now wider base OS support, covering Amazon Linux, CentOS 6 & 7
and also Ubuntu. All AMIs are now created using the same receipes. All previously capabilites exisit and the
changes should be non-instrusive.


0.0.22
------
- updates:``ami``: Pulled latest CentOS6 errata
- feature:``cfncluster``: Support for specifiying MasterServer and ComputeFleet root volume size
- bugfix:``cfncluster-node``: Fix for SGE parallel job detection
- bugfix:``ami``: Removed ZFS packages
- bugfix:``cfncluster-node``: Fix torque node additon with pbs_server restart
- updates:``ami``: Updated Chef client to 12.4.1 + berkshelf
- bugfix:``cfncluster``: Only count pending jobs with status 'qw' (Kenneth Daily <kmdaily@gmail.com>)
- bugfix::``cli``: Updated example config file (John Lilley <johnbot@caltech.edu>)
- bugfix::``cli``: Fixed typo on scaling cooldown property (Nelson R Monserrate <MonserrateNelson@JohnDeere.com>)

0.0.21
------
- feature:``cfncluster``: Support for dedicated tenancy
- feature:``cfncluster``: Support for customer provided KMS keys (EBS and ephemeral)
- updates:``ami``: Pulled latest CentOS6 errata
- feature:``cfncluster``: Support for M4 instances

0.0.20
------
- feature:``cfncluster``: Support for D2 instances
- updates:``ami``: Pulled latest CentOS6 errata
- updates:``ami``: Pulled latest cfncluster-node package
- updates:``ami``: Pulled latest ec2-udev-rules package
- updates:``ami``: Pulled latest NVIDIA driver 346.47
- updates:``ami``: Removed cfncluster-kernel repo and packages
- updates:``ami``: Updated Chef client to 12.2.1 + berkshelf

0.0.19
------
- feature:``cli``: Added configure command; easy config setup
- updates:``docs``: Addtional documentation for configuration options
- updates:``ami``: Pulled latest CentOS6 errata
- bugfix:``cfncluster``: Fixed issue with nodewatcher not scaling down

0.0.18
------
- updates:``ami``: Custom CentOS 6 kernel repo added, support for >32 vCPUs
- feature:``ami``: Chef 11.x client + berkshelf
- feature:``cfncluster``: Support for S3 based pre/post install scripts
- feature:``cfncluster``: Support for EBS shared directory variable
- feature:``cfncluster``: Support for C4 instances
- feature:``cfncluster``: Support for additional VPC security group
- updates:``ami``: Pulled latest NVIDIA driver 340.65
- feature:``cli``: Added support for version command
- updates:``cli``: Removed unimplemented stop command from CLI

0.0.17
------
- updates:``ami``: Pulled latest CentOS errata. Now CentOS 6.6.
- updates:``ami``: Updated SGE to 8.1.6
- updates:``ami``: Updates openlava to latest pull from GitHub
- bugfix:``ami``: Fixed handling of HTTP(S) proxies
- feature:``ami``: Moved sqswatcher and nodewatcher into Python package cfncluster-node

0.0.16
------
- feature:``cfncluster``: Support for GovCloud region
- updates:``cli``: Improved error messages parsing config file

0.0.15
------

- feature:``cfncluster``: Support for Frankfurt region
- feature:``cli``: status call now outputs CREATE_FAILED messages for stacks in error state
- update:``cli``: Improved tags and extra_parameters on CLI
- bugfix:``cli``: Only check config sanity on calls that mutate stack
- updates:``ami``: Pulled latest CentOS errata

0.0.14
------
- feature:``cli``: Introduced sanity_check feature for config
- updates:``cli``: Simplified EC2 key pair config
- feature:``cfncluster``: Scale up is now driven by two policies; enables small and large scaling steps
- feature:``cfnlcuster``: Introduced initial support for CloudWatch logs in us-east-1
- updates:``ami``: Moved deamon handling to supervisord
- updates:``ami``: Pulled latest CentOS errata

0.0.13
------
- bugfix:``cli``: Fixed missing AvailabilityZone for "update" command

0.0.12
------

- updates:``cli``: Simplfied VPC config and removed multi-AZ

0.0.11
------

- updates:``ami``: Pulled latest CentOS errata
- updates:``ami``: Removed DKMS Lustre; replaced with Intel Lustre Client

0.0.10
------

- updates:``ami``: Pulled latest CentOS errata
- updates:``ami``: Updated packages to match base RHEL AMI's
- feature:``cli``: Improved region handling and added support for AWS_DEFAULT_REGION

0.0.9
-----

- feature:``cfncluster``: Added s3_read_resource and s3_read_write_resource options to cluster config
- feature:``cfncluster``: cfncluster is now available in all regions
- updates:``ami``: Pulled latest CentOS errata
- feature:``cfncluster``: Added ephemeral_dir option to cluster config

0.0.8
-----

- feature:``cfncluster``: Added support for new T2 instances
- updates:``cfncluster``: Changed default instance sizes to t2.micro(free tier)
- updates:``cfncluster``: Changed EBS volume default size to 20GB(free tier)
- updates:``ami``: Pulled latest CentOS errata
- bugfix:``cfncluster``: Fixed issues with install_type option(removed)

0.0.7
-----

- feature:``cfncluster``: Added option to encrypt ephemeral drives with in-memory keys
- feature:``cfncluster``: Support for EBS encryption on /shared volume
- feature:``cfncluster``: Detect all ephemeral drives, stripe and mount as /scratch
- feature:``cfncluster``: Support for placement groups
- feature:``cfncluster``: Support for cluster placement logic. Can either be cluster or compute.
- feature:``cfncluster``: Added option to provides arguments to pre/post install scripts
- feature:``cfncluster``: Added DKMS support for Lustre filesystems - http://zfsonlinux.org/lustre.html
- bugfix:``cli``: Added missing support from SSH from CIDR range
- bugfix:``cfncluster``: Fixed Ganglia setup for ComputeFleet
- updates:``SGE``: Updated to 8.1.7 - https://arc.liv.ac.uk/trac/SGE
- updates:``Openlava``: Updated to latest Git for Openlava 2.2 - https://github.com/openlava/openlava

0.0.6
-----

- feature:Amazon EBS: Added support for Amazon EBS General Pupose(SSD) Volumes; both AMI and /shared
- bugfix:``cli``: Fixed boto.exception.NoAuthHandlerFound when using credentials in config
- updates:CentOS: Pulled in latest errata to AMI. See amis.txt for latest ID's.

0.0.5
-----

- Release on GitHub and PyPi
