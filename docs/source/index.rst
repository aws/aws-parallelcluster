.. cfncluster documentation master file, created by
   sphinx-quickstart on Wed Nov  5 07:56:13 2014.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.


cfncluster
##########

cfncluster is a framework that deploys and maintains High Performance Clusters (HPC) on AWS. It is reasonably agnostic to what the cluster is for and can easily be extended to support different frameworks. The CLI is stateless, everything is done using CloudFormation or resources within AWS.

.. toctree::
    :maxdepth: 2

    getting_started
    welcome
    configuration
    functional    

Getting Started
---------------

If you've never used ``cfncluster`` before, you should read the :doc:`Getting Started with cfncluster <getting_started>` guide to get familiar with ``cfncluster`` & its usage.

Additional Docs
---------------

* :doc:`pre & post install actions <pre_post_install>`
* :doc:`cfncluster auto-scaling <autoscaling>`
* :doc:`AWS services used in cfncluster <aws_services>`
* :doc:`cfncluster networking configurations <networking>`
* :doc:`working with S3 <s3_resources>`

Additional Resources
--------------------

* `cfncluster Source Repository`_
* `cfncluster Issue Tracker`_
* `cfncluster Webcast - HPC Scalability in the Cloud`_

.. _cfncluster Issue Tracker: https://github.com/awslabs/cfncluster/issues
.. _cfncluster Source Repository: https://github.com/awslabs/cfncluster
.. _cfncluster Webcast - HPC Scalability in the Cloud: https://www.youtube.com/watch?v=iHtzy6_WytE

Indices and tables
==================

* :ref:`genindex`
* :ref:`search`
