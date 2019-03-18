.. _pre_post_install:

Custom Bootstrap Actions
========================

AWS ParallelCluster can execute arbitrary code from an S3 bucket either before (pre) or after (post) the main
bootstrap action during cluster creation.  The pre- and post-install scripts will be executed as root and
can be written in any script language supported by the cluster operating system.
This is typically `bash` or `python`.

The pre-install script is executed before any cluster deployment bootstrap action such as configuring NAT,
building EBS volumes, and enabling the chosen scheduler.
Typical pre-install actions may include modifying storage, adding extra users, or installing additional packages.

post-install actions are invoked after the cluster bootstrap process is complete as the last action before an
instance is considered complete. Typical post-install actions may include changing scheduler settings, modifying
shared storage, or installing additional packages.

Arguments can be passed to scripts by specifying them in the config.  They must be passed double-quoted to the
pre/post-install actions.

If a pre/post-install actions fails, the instance bootstrap will be considered failed and will not continue.
Success is signalled with an exit code of 0.  Any other exit code will be considered a failure.

Configuration
-------------

The following config settings are used to define pre/post-install actions and arguments.  All parameters are optional
and are *not* required for a basic cluster installation.

::

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
The first two arguments ``$0`` and ``$1`` are reserved for the script name and url.

::

    $0 => the script name
    $1 => s3 url
    $n => args set by pre/post_install_args

Example
-------

Here is an example of how to create a simple post-install script to install some R packages on a cluster.

1. Create a script. For the R example, see below:

::

    #!/bin/bash

    yum -y install --enablerepo=epel R

2. Upload the script with the correct permissions to S3:

::

$ chmod 0755 myscript.sh
$ aws s3 cp --acl public-read /path/to/myscript.sh s3://<bucket-name>/myscript.sh

3. Update the AWS ParallelCluster configuration file to include the new post install action:

::

    [cluster default]
    ...
    post_install = https://<bucket-name>.s3.amazonaws.com/myscript.sh

If the bucket does not have public-read permission, use ``s3`` as the URL scheme.

::

    [cluster default]
    ...
    post_install = s3://<bucket-name>/myscript.sh


4. Launch a new cluster stack:

``pcluster create mycluster``
