.. _ami_customization:

.. toctree::
   :maxdepth: 2

#########################################
Building a custom AWS ParallelCluster AMI
#########################################

.. warning::
    Building a custom AMI is not the recommended approach for customizing AWS ParallelCluster.

    Once you build your own AMI, you will no longer receive updates or bug fixes with future releases of AWS
    ParallelCluster. You will need to repeat the steps used to create your custom AMI with each new AWS ParallelCluster
    release.

Before reading any further, take a look at the :doc:`../pre_post_install` section of the documentation to determine
if the modifications you wish to make can be scripted and supported with future AWS ParallelCluster releases.

While not ideal, there are a number of scenarios where building a custom AMI for AWS ParallelCluster is necessary. This
tutorial will guide you through the process.

How to customize the AWS ParallelCluster AMI
============================================

There are three alternative ways to use a custom AWS ParallelCluster AMI, two of them require to build a new AMI that
will be available under your AWS account and one does not require to build anything in advance:

- modify an AWS ParallelCluster AMI, when you want to install your software on top of an official AWS ParalleCluster AMI
- build a custom AWS ParallelCluster AMI, when you have an AMI with customization and software already in place, and
  want to build an AWS ParalleCluster AMI on top of it
- use a Custom AMI at runtime, when you don't want to create anything in advance, AWS ParallelCluster will install
  everything it needs at runtime (during cluster creation time and scale-up time)

Feel free to select the appropriate method based on your needs.

Modify an AWS ParallelCluster AMI
---------------------------------

This is the safest method as the base AWS ParallelCluster AMI is often updated with new releases. This AMI has all of
the components required for AWS ParallelCluster to function installed and configured and you can start with this as the
base.

    #. Find the AMI which corresponds to the region you will be utilizing from the AMI list.
        .. warning::
            The AMI list to use must match the version of AWS ParallelCluster, for example:

            - for AWS ParallelCluster 2.3.1 -> https://github.com/aws/aws-parallelcluster/blob/v2.3.1/amis.txt
            - for AWS ParallelCluster 2.2.1 -> https://github.com/aws/aws-parallelcluster/blob/v2.2.1/amis.txt
            - for AWS ParallelCluster 2.1.1 -> https://github.com/aws/aws-parallelcluster/blob/v2.1.1/amis.txt
            - for CfnCluster 1.6.1 -> https://github.com/aws/aws-parallelcluster/blob/v1.6.1/amis.txt

    #. Within the EC2 Console, choose "Launch Instance".
    #. Navigate to "Community AMIs", and enter the AMI id for your region into the search box.
    #. Select the AMI, choose your instance type and properties, and launch your instance.
    #. Log into your instance using the OS user and your SSH key.
    #. Customize your instance as required
    #. Run the following command to prepare your instance for AMI creation::

        sudo /usr/local/sbin/ami_cleanup.sh

    #. Stop the instance
    #. Create a new AMI from the instance
    #. Enter the AMI id in the :ref:`custom_ami_section` field within your cluster configuration.

Build a Custom AWS ParallelCluster AMI
--------------------------------------

If you have an AMI with a lot of customization and software already in place, you can apply the changes needed by AWS
ParallelCluster on top of it.

For this method you have to install the following tools in your local system, together with the AWS ParallelCluster CLI:

    #. Packer: grab the latest version for your OS from `Packer website <https://www.packer.io/downloads.html>`_ and
       install it
    #. ChefDK: grab the latest version for your OS from `ChefDK website <https://downloads.chef.io/chefdk/>`_ and
       install it

Verify that the commands 'packer' and 'berks' are available in your PATH after the above tools installation.

You need to configure your AWS account credentials so that Packer can make calls to AWS API operations on your behalf.
The minimal set of required permissions necessary for Packer to work are documented in the `Packer doc
<https://www.packer.io/docs/builders/amazon.html#iam-task-or-instance-role>`_.

Now you can use the command 'createami' of the AWS ParallelCluster CLI in order to build an AWS ParallelCluster AMI
starting from the one you provide as base::

        pcluster createami --ami-id <BASE AMI> --os <BASE OS AMI>

.. warning::
    You cannot use a ParalleCluster AMI as <BASE AMI> for the create command or the create will fail.

For other parameters, please consult the command help::

        pcluster createami -h

The command executes Packer, which does the following steps:

    #. Launch an instance using the base AMI provided.
    #. Apply the AWS ParallelCluster cookbook to the instance, in order to install software and perform other necessary
       configuration tasks.
    #. Stop the instance.
    #. Creates an new AMI from the instance.
    #. Terminates the instance after the AMI is created.
    #. Outputs the new AMI ID string to use to create your cluster.

To create your cluster enter the AMI id in the :ref:`custom_ami_section` field within your cluster configuration.

.. note:: The instance type to build a custom AWS ParallelCluster AMI is a t2.xlarge and does not qualify for the AWS
    free tier. You are charged for any instances created when building this AMI.

Use a Custom AMI at runtime
---------------------------

If you don't want to create anything in advance you can just use your AMI and create a AWS ParallelCluster from that.

Please notice that in this case the AWS ParallelCluster creation time will take longer, as it will install every
software needed by AWS ParallelCluster at cluster creation time.
Also scaling up for every new node will need more time.

    #. Enter the AMI id in the :ref:`custom_ami_section` field within your cluster configuration.
