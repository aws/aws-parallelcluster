.. _custom_cookbook:

################################################
Setting Up a Custom AWS ParallelCluster Cookbook
################################################

.. warning::
    The following are instructions for use a custom version of the AWS ParallelCluster cookbook recipes.
    This is an advanced method of customizing AWS ParallelCluster, with many hard to debug pitfalls.
    The AWS ParallelCluster team highly recommends using :doc:`pre_post_install` scripts for customization,
    as post install hooks are generally easier to debug and more portable across releases of AWS ParallelCluster.

Steps
=====

#. Clone the cookbook and make changes ::

        $ git clone https://github.com/aws/aws-parallelcluster-cookbook.git
        ...
        # Make changes to cookbook

#. Upload the cookbook, changing ``[your_bucket]`` to a bucket you own ::

        $ cd aws-parallelcluster-cookbook
        $ /bin/bash util/uploadCookbook.sh --bucket [your_bucket] --srcdir .

#. From the output above, add the following variable to the AWS ParallelCluster config file, under the ``[cluster ...]`` section ::

        custom_chef_cookbook = https://s3.amazonaws.com/your_bucket/cookbooks/aws-parallelcluster-cookbook-2.2.1.tgz

.. spelling::
    md
