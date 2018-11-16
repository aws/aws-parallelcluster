..
    AWS ParallelCluster documentation master file, created by
    sphinx-quickstart on Wed Nov  5 07:56:13 2014.
    You can adapt this file completely to your liking, but it should at least
    contain the root `toctree` directive.


AWS ParallelCluster
###################

AWS ParallelCluster is an AWS supported Open Source cluster management tool that makes it easy for you to deploy and
manage High Performance Computing (HPC) clusters in the AWS cloud.
Built on the Open Source CfnCluster project, AWS ParallelCluster enables you to quickly build an HPC compute
environment in AWS.
It automatically sets up the required compute resources and a shared filesystem and offers a variety of batch
schedulers such as AWS Batch, SGE, Torque, and Slurm.
AWS ParallelCluster facilitates both quick start proof of concepts (POCs) and production deployments.
You can build higher level workflows, such as a Genomics portal that automates the entire DNA sequencing workflow, on
top of AWS ParallelCluster.

.. toctree::
    :maxdepth: 2

    getting_started
    working
    configuration
    functional
    tutorials
    development

Getting Started
---------------

If you've never used ``AWS ParallelCluster`` before, you should read the :doc:`Getting Started with AWS ParallelCluster
<getting_started>` guide to get familiar with ``pcluster`` & its usage.

Additional Docs
---------------

* :doc:`pre & post install actions <pre_post_install>`
* :doc:`AWS ParallelCluster auto-scaling <autoscaling>`
* :doc:`AWS services used in AWS ParallelCluster <aws_services>`
* :doc:`AWS ParallelCluster networking configurations <networking>`
* :doc:`working with S3 <s3_resources>`

Additional Resources
--------------------

* `AWS ParallelCluster Source Repository`_
* `AWS ParallelCluster Issue Tracker`_
* `CfnCluster Webcast - ResearchCloud - CfnCluster and Internet2 for Enterprise HPC`_

.. _AWS ParallelCluster Issue Tracker: https://github.com/aws/aws-parallelcluster/issues
.. _AWS ParallelCluster Source Repository: https://github.com/aws/aws-parallelcluster
.. _CfnCluster Webcast - ResearchCloud - CfnCluster and Internet2 for Enterprise HPC:
    https://www.youtube.com/watch?v=2WJcKwAChHE&feature=youtu.be&t=22m17s

Indices and tables
==================

* :ref:`genindex`
* :ref:`search`
