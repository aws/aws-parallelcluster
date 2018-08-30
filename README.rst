CfnCluster
==========

.. image:: https://travis-ci.org/awslabs/cfncluster.png?branch=develop
   :target: https://travis-ci.org/awslabs/cfncluster
   :alt: Build Status

CfnCluster ("cloud formation cluster") is a framework that deploys and
maintains high performance computing clusters on Amazon Web Services
(AWS). Developed by AWS, CfnCluster facilitates both quick start proof
of concepts (POCs) and production deployments. CfnCluster supports
many different types of clustered applications and can easily be
extended to support different frameworks. The CLI is stateless,
everything is done using CloudFormation or resources within AWS.

Documentation
=============

Documentation is part of the project and is published to -
https://cfncluster.readthedocs.io/. Of most interest to new users is
the Getting Started Guide -
https://cfncluster.readthedocs.io/en/latest/getting_started.html.

Issues
======

Please open a GitHub issue for any feedback or issues:
https://github.com/awslabs/cfncluster.  There is also an active AWS
HPC forum which may be helpful:https://forums.aws.amazon.com/forum.jspa?forumID=192.

CfnCluster 1.6 IAM Change
=========================
Between CfnCluster 1.5.3 and 1.6.0 we made a change to the CfnClusterInstancePolicy that adds “s3:GetObject” permissions on objects in <REGION>-cfncluster bucket.
If you’re using a custom policy (e.g. you specify "ec2_iam_role" in your config) be sure it includes this new permission. See https://cfncluster.readthedocs.io/en/latest/iam.html

CfnCluster 1.5 IAM Change
=========================
Between CfnCluster 1.4.2 and 1.5.0 we made a change to the CfnClusterInstancePolicy that adds “ec2:DescribeVolumes” permissions. If you’re using a custom policy (e.g. you specify "ec2_iam_role" in your config) be sure it includes this new permission. See https://cfncluster.readthedocs.io/en/latest/iam.html

CfnCluster 1.2 and Earlier
==========================

For various security (on our side) and maintenance reasons, CfnCluster
1.2 and earlier have been deprecated.  AWS-side resources necessary to
create a cluster with CfnCluster 1.2 or earlier are no longer
available.  Existing clusters will continue to operate, but new
clusters can not be created.
