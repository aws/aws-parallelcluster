.. _pre_post_install:

Custom Bootstrap Actions
========================

AWS ParallelCluster can execute arbitrary code either before (preinstall) or after (postinstall)
the main bootstrap process.  These scripts are typically stored in S3 and accessed via HTTPS.
They are executed as root and can be written in any scripting language supported by the
cluster operating system, typically `bash` or `python`.

Typical preinstall actions may include modifying storage, adding extra users, or installing
additional software packages before any cluster deployment bootstrap processes are initiated
such as configuring NAT, EBS, and the scheduler.

Typical postinstall actions may include changing scheduler settings, mounting additional storage,
or installing extra software packages.  postinstall actions are called after the cluster bootstrap
is complete as the last action before an instance is considered complete and ready for service.

Arguments can be passed to the scripts by specifying them in the config.  These will be passed
double-quoted to the pre/postinstall actions.

If a pre/postinstall actions fails, the instance bootstrap will be considered to have failed
and will not continue.  Success is signalled with an exit code of 0.  Any other exit code
is considered to indicate failure.

Configuration
-------------

The following config settings are used to define pre/postinstall actions and arguments.
These options are optional and are not required for basic cluster install. ::

    # URL to a preinstall script. This is executed before any of the boot_as_* scripts are run
    # (defaults to NONE)
    pre_install = NONE
    # Arguments to be passed to preinstall script
    # (defaults to NONE)
    pre_install_args = NONE
    # URL to a postinstall script. This is executed after any of the boot_as_* scripts are run
    # (defaults to NONE)
    post_install = NONE
    # Arguments to be passed to postinstall script
    # (defaults to NONE)
    post_install_args = NONE

Arguments
---------
The first two arguments ``$0`` and ``$1`` are reserved for the script name and url. ::

    $0 => the script name
    $1 => s3 url
    $n => args set by pre/post_install_args

Example #1
----------

This example creates a postinstall script that will install 'R' on a cluster:

1. Create a postinstall script to install R.  If a postinstall script already exists,
append this code snippet without the shebang:
::

    #!/bin/bash

    yum -y install --enablerepo=epel R

2. Upload the script with the correct permissions to S3.
::

``aws s3 cp --acl public-read /path/to/myscript.sh s3://<bucket-name>/myscript.sh``

3. Update the AWS ParallelCluster configuration file to include the new postinstall action.
::

    [cluster default]
    ...
    post_install = https://<bucket-name>.s3.amazonaws.com/myscript.sh

If the bucket does not have public-read permission use ``s3`` as the URL scheme.
::

    [cluster default]
    ...
    post_install = s3://<bucket-name>/myscript.sh


4. Launch the cluster.
::

``pcluster create mycluster``


Example #2
----------
This example will apply tags to any EBS volume associated with the cluster's master and compute instances:

1. Append the following code snippet to the postinstall script.  If a postinstall script
already exists, append this code snippet without the shebang:
::

    #!/bin/bash
    #
    # Parse the InstanceId and RootDiskId from EC2 instance metadata.
    # Apply some tags to any EBS volumes that belong to the cluster stack.
    #
    AWS_INSTANCE_ID=$(ec2-metadata -i | awk '{print $2}')
    AWS_PCLUSTER_NAME=$(cat /etc/parallelcluster/cfnconfig | grep stack_name | sed -e "s/stack_name=parallelcluster-//g")
    AWS_REGION=$(ec2-metadata -z | awk '{print $2}' | sed 's/.$//')
    ROOT_DISK_ID=$(aws --region ${AWS_REGION} ec2 describe-volumes --filter "Name=attachment.instance-id,Values=${AWS_INSTANCE_ID}" --query "Volumes[].VolumeId" --out text)
    aws --region ${AWS_REGION} ec2 create-tags --resources ${ROOT_DISK_ID} --tags Key=ClusterStackName,Value=$AWS_PCLUSTER_NAME Key=MountedByInstance,Value=${AWS_INSTANCE_ID}

2. Upload the script with the correct permissions to S3.
::

``aws s3 cp --acl public-read /path/to/myscript.sh s3://<bucket-name>/myscript.sh``

3. Update the AWS ParallelCluster configuration file to include the new postinstall action.
::

    [cluster default]
    ...
    post_install = https://<bucket-name>.s3.amazonaws.com/myscript.sh

If the bucket does not have public-read permissions, use ``s3`` as the URL scheme.
::

    [cluster default]
    ...
    post_install = s3://<bucket-name>/myscript.sh

4. Launch the cluster.
::

``pcluster create mycluster``

.. spelling::
   postinstall
   preinstall
