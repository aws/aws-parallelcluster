.. _tutorials_encrypted_kms_fs:

.. toctree::
   :maxdepth: 2

#####################################
Disk Encryption with a Custom KMS Key
#####################################

AWS ParallelCluster supports the configuration options ``ebs_kms_key_id``, which allows you to
provide a custom KMS key for EBS Disk encryption. To use it you'll need to specify a ``ec2_iam_role``.

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

Here's an example with EBS: ::

   [cluster default]
   ...
   ebs_settings = custom1
   ec2_iam_role = ParallelClusterInstanceRole

   [ebs custom1]
   shared_dir = vol1
   ebs_kms_key_id = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   volume_type = io1
   volume_iops = 200
