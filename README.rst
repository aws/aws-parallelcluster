CfnCluster
==========

.. image:: https://travis-ci.org/awslabs/cfncluster.png?branch=develop
   :target: https://travis-ci.org/awslabs/cfncluster
   :alt: Build Status

CfnCluster ("cloud formation cluster") is a framework that deploys and maintains high performance computing clusters on Amazon Web Services (AWS). Developed by AWS, CfnCluster facilitates both quick start proof of concepts (POCs) and production deployments. CfnCluster supports many different types of clustered applications and can easily be extended to support different frameworks. The CLI is stateless, everything is done using CloudFormation or resources within AWS.

Known Issues
============

* CfnCluster 1.3.2 supports the I3 and F1 instance families.  However,
  it will not automatically setup a single, RAIDed volume across all
  available instance store volumes (like it will for other instance
  families which support instance storage).  This will be fixed in a
  future release.

Documentation
=============

Documentation is part of the project and is published to - https://cfncluster.readthedocs.io/. Of most interest to new users is the Getting Started Guide - https://cfncluster.readthedocs.io/en/latest/getting_started.html.

Issues
======

Please open a GitHub issue for any feedback or issues:
https://github.com/awslabs/cfncluster.  There is also an active AWS
HPC forum which may be helpful:https://forums.aws.amazon.com/forum.jspa?forumID=192.
