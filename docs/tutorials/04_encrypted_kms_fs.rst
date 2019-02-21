.. _tutorials_encrypted_kms_fs:

.. toctree::
   :maxdepth: 2

#####################################
Disk Encryption with a Custom KMS Key
#####################################

AWS ParallelCluster supports the configuration options ``ebs_kms_key_id`` and ``fsx_kms_key_id``, which allow you to
provide a custom KMS key for EBS Disk encryption or FSx Lustre. To use them you'll need to specify a ``ec2_iam_role``.

In order for the cluster to create, the KMS key needs to know the name of the cluster's role. This prevents you from
using the role created on cluster create, requiring a custom ``ec2_iam_role``.


Creating the Role
=================

First you'll need to create a policy:

1. Go to the IAM Console: https://console.aws.amazon.com/iam/home
2. Under Policies, create a policy, click the JSON tab
3. As the policy's body, paste in the :doc:`Instance Policy<../iam>`
   Make sure to replace all occurrences of ``<AWS ACCOUNT ID>`` and ``<REGION>``
4. Call it ``ParallelClusterInstancePolicy`` and click "Create Policy"

Next create a role:

1. Under Roles, create a role
2. Click ``EC2`` as the trusted entity
3. Under Permissions, search for the ``ParallelClusterInstancePolicy`` role you just created and attach it.
4. Name it ``ParallelClusterRole`` and click "Create Role"

Give your Key Permissions
=========================

In the IAM Console > Encryption Keys > click on your key.

Click "Add User" and search for the `ParallelClusterInstanceRole`` you just created. Attach it.

Creating the Cluster
====================

Now create a cluster, here's an example of a cluster with encrypted ``Raid 0`` drives: ::

   [cluster default]
   ...
   raid_settings = rs
   ec2_iam_role = ParallelClusterInstanceRole

   [raid rs]
   shared_dir = raid
   raid_type = 0
   num_of_raid_volumes = 2
   volume_size = 100
   encrypted = true
   ebs_kms_key_id = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

Here's an example with FSx Lustre file system: ::

   [cluster default]
   ...
   fsx_settings = fs
   ec2_iam_role = ParallelClusterInstanceRole

   [fsx fs]
   shared_dir = /fsx
   storage_capacity = 3600
   imported_file_chunk_size = 1024
   export_path = s3://bucket/folder
   import_path = s3://bucket
   weekly_maintenance_start_time = 1:00:00
   fsx_kms_key_id = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

Similar configuration applies for EBS and FSx based file systems.
