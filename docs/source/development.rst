.. _development:

Development
###########

Here you can find guides for getting started with the development of CfnCluster.

.. warning::
    The following guides are instructions for building a custom AMI, use a custom version of the cookbook recipes or a custom CfnCluster Node package.
    These are advanced method of customizing CfnCluster, with many hard to debug pitfalls.
    The CfnCluster team highly recommends using :doc:`pre_post_install` scripts for customization, as post install hooks are generally easier to debug and more portable across releases of CfnCluster.

.. toctree::

    ami_development
    custom_cookbook
    custom_node_package
