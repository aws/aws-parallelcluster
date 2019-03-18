..
    AWS ParallelCluster documentation master file, created by
    sphinx-quickstart on Wed Nov  5 07:56:13 2014.
    You can adapt this file completely to your liking, but it should at least
    contain the root `toctree` directive.


AWS ParallelCluster
###################

AWS ParallelCluster is an AWS-supported Open Source cluster management tool that makes it easy to deploy and
manage High Performance Computing (HPC) clusters in the AWS cloud.

AWS ParallelCluster supports the following features:

- Multiple Linux flavors including Amazon Linux, CentOS, and Ubuntu.
- Configurable autoscaling of compute resources.
- Custom AMIs.
- Shared file systems built from EBS, EFS, and FSxL (Lustre) volumes.
- EBS RAID functionality.
- Private subnet deployments.
- Multiple HPC schedulers including AWS Batch, Grid Engine, Torque, and Slurm.

AWS ParallelCluster facilitates both quick start proof-of-concepts (POCs) and massive production deployments.
It can be used to orchestrate higher level workflow use cases such as automated DNA sequencing pipelines,
global weather forecasting, cryptography, fluid dynamics simulations, jet engine design, credit card fraud
detection, insurance risk modeling, and protein-ligand docking analysis.

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

If you have never used ``AWS ParallelCluster`` before, please read the :doc:`Getting Started with AWS ParallelCluster
<getting_started>` guide to get familiar with ``pcluster`` and its usage.

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
