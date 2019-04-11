.. _pre_post_install:

Custom Bootstrap Actions
========================

AWS ParallelCluster can execute arbitrary code either before(pre) or after(post) the main bootstrap action during
cluster creation. This code is typically stored in S3 and accessed via HTTP(S) during cluster creation. The code will
be executed as root and can be in any script language supported by the cluster OS, typically `bash` or `python`.

Pre-install actions are called before any cluster deployment bootstrap such as configuring NAT, EBS and the scheduler.
Typical pre-install actions may include modifying storage, adding extra users or packages.

Post-install actions are called after cluster bootstrap is complete, as the last action before an instance is
considered complete. Typical post-install actions may include changing scheduler settings, modifying storage or
packages.

Arguments can be passed to scripts by specifying them in the config.

If a pre/post-install actions fails, then the instance bootstrap will be considered failed and it will not continue.
Success is signalled with an exit code of 0, any other exit code will be considered a fail.

It is possible to differentiate between master and compute nodes execution by sourcing
the ``/etc/parallelcluster/cfnconfig`` file and evaluating the ``cfn_node_type`` environment variable,
whose possible values are ``MasterServer`` and ``ComputeFleet`` for the master and compute node respectively.

::

    #!/bin/bash

    . "/etc/parallelcluster/cfnconfig"

    case "${cfn_node_type}" in
        MasterServer)
            echo "I am the master" >> /tmp/master.txt
        ;;
        ComputeFleet)
            echo "I am a compute node" >> /tmp/compute.txt
        ;;
        *)
            ;;
    esac

Configuration
-------------

The following config settings are used to define pre/post-install actions and arguments. All options are optional and
are not required for basic cluster install.

::

    # URL to a preinstall script. This is executed before any of the boot_as_* scripts are run (defaults to NONE)
    pre_install = NONE
    # Arguments to be passed to preinstall script (defaults to NONE)
    pre_install_args = NONE
    # URL to a postinstall script. This is executed after any of the boot_as_* scripts are run (defaults to NONE)
    post_install = NONE
    # Arguments to be passed to postinstall script (defaults to NONE)
    post_install_args = NONE

Arguments
---------
The first two arguments ``$0`` and ``$1`` are reserved for the script name and url.
If the pre/post_install_args variable contains a list of parameters it must be double quoted. See example below.

::

    $0 => the script name
    $1 => s3 url
    $n => args set by pre/post_install_args

Output
------
The output of the pre/post-install scripts can be found in the ``/var/log/cfn-init.log``
and ``/var/log/cfn-init-cmd.log`` files.

Example
-------

The following are some steps to create a simple post install script that installs a list of packages, specified by the
``post_install_args`` configuration parameter, in a cluster.

1. Create a script

::

    #!/bin/bash

    echo "post-install script has $# arguments"
    for arg in "$@"
    do
        echo "arg: ${arg}"
    done

    yum -y install "${@:2}"

2. Upload the script with the correct permissions to S3

``aws s3 cp --acl public-read /path/to/myscript.sh s3://<bucket-name>/myscript.sh``

3. Update AWS ParallelCluster config to include the new post install action.

::

    [cluster default]
    ...
    post_install = https://<bucket-name>.s3.amazonaws.com/myscript.sh
    post_install_args = "R curl wget"

If the bucket does not have public-read permission use ``s3`` as URL scheme.

::

    [cluster default]
    ...
    post_install = s3://<bucket-name>/myscript.sh
    post_install_args = "R curl wget"

4. Launch a cluster

``pcluster create mycluster``


5. Verify the output

::

    $ less /var/log/cfn-init.log
    2019-04-11 10:43:54,588 [DEBUG] Command runpostinstall output: post-install script has 4 arguments
    arg: s3://eu-eu-west-1/test.sh
    arg: R
    arg: curl
    arg: wget
    Loaded plugins: dkms-build-requires, priorities, update-motd, upgrade-helper
    Package R-3.4.1-1.52.amzn1.x86_64 already installed and latest version
    Package curl-7.61.1-7.91.amzn1.x86_64 already installed and latest version
    Package wget-1.18-4.29.amzn1.x86_64 already installed and latest version
    Nothing to do
