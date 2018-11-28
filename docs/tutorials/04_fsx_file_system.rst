.. _fsx_file_system:

.. toctree::
   :maxdepth: 2

##############################
Using a FSx Lustre File System
##############################

This guides you through the process of setting up a **Centos 7** cluster with a Lustre file system attached. For more
information on FSx, please see their `docs <https://docs.aws.amazon.com/fsx/latest/LustreGuide/getting-started.html>`_.

Step 1:
=======

If you don't have a file system you can create one with the AWS cli. Ensure that the subnet is the same as what you use
for your cluster.

You can optionally specify the ``--lustre-configuration`` flag to specify an S3 bucket to load data from. ::

    $ aws fsx create-file-system --file-system-type LUSTRE --storage-capacity 3600 --subnet-ids [CLUSTER SUBNET] \
      --lustre-configuration ImportPath=s3://[YOUR BUCKET]

Wait for the file system to finish creating, then grab the ``DNSName``, it contains the file system id, which you'll
need in the next step. ::

    $ aws fsx describe-file-systems

Step 2:
=======

Create a file that contains:

.. literalinclude:: code_samples/fsx/fsx_postinstall.sh
   :language: bash

Upload that file to an S3 bucket ::

    aws s3 cp fsx_postinstall.sh s3://[your_bucket]

Step 3:
=======

Using the file system id you found above, for example ``fs-00079dd40d69348ce``, and the mount point you want, modify
 your config to include: ::

    [cluster fsx]
    ...
    base_os = centos7
    s3_read_resource = arn:aws:s3:::[your_bucket]/fsx_postinstall.sh
    post_install = s3://[your_bucket]/fsx_postinstall.sh
    post_install_args = fs-00079dd40d69348ce /fsx

Create the cluster ::

    $ pcluster create fsx --cluster-template fsx --norollback

Log in and see that the ``/fsx`` directory has successfully mounted: ::

    $ pcluster ssh fsx
    $ df
    Filesystem              1K-blocks    Used  Available Use% Mounted on
    ...
    172.31.23.131@tcp:/fsx 3547698816   13824 3547678848   1% /fsx
