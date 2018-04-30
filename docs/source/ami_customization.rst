.. _ami_customization:

.. toctree::
   :maxdepth: 2

################################
Building a custom CfnCluster AMI
################################

.. warning::
    Building a custom AMI is not the recommended approach for customizing CfnCluster.

    Once you build your own AMI, you will no longer receive updates or bug fixes with future releases of CfnCluster.  You will need to repeat the steps used to create your custom AMI with each new CfnCluster release.

Before reading any further, take a look at the :doc:`pre_post_install` section of the documentation to determine if the modifications you wish to make can be scripted and supported with future CfnCluster releases

While not ideal, there are a number of scenarios where building a custom AMI for CfnCluster is necessary.  This tutorial will guide you through the process.

How to customize the CfnCluster AMI
===================================

The base CfnCluster AMI is often updated with new releases.  This AMI has all of the components required for CfnCluster to function installed and configured.  If you wish to customize an AMI for CfnCluster, you must start with this as the base.

    #. Find the AMI which corresponds with the region you will be utilizing in the list here: https://github.com/awslabs/cfncluster/blob/master/amis.txt.  
    #. Within the EC2 Console, choose "Launch Instance".
    #. Navigate to "Community AMIs", and enter the AMI id for your region into the search box.
    #. Select the AMI, choose your instance type and properties, and launch your instance.
    #. Log into your instance using the ec2-user and your SSH key.
    #. Customize your instance as required
    #. Run the following command to prepare your instance for AMI creation::

        sudo /usr/local/sbin/ami_cleanup.sh

    #. Stop the instance
    #. Create a new AMI from the instance
    #. Enter the AMI id in the :ref:`custom_ami_section` field within your cluster configuration.
