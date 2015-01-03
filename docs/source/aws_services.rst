.. _aws_services:

AWS Services used in cfncluster
===============================

The following Amazon Web Services(AWS) services are used in cfncluster. 

* CloudFormation
* IAM
* SNS
* SQS
* EC2
* AutoScaling
* EBS
* Cloudwatch
* S3
* DynamoDB

CloudFormation
--------------

CloudFormation is the core service used by cfncluster. Each cluster is representated as a stack. All resources required by the cluster are defined within the cfncluster CloudFormation template. cfncluster cli commands typically map to CloudFormation stack commands, such as create, update and delete. Instances launched within a cluster make HTTPS calls to the CloudFormation Endpoint for the region the cluster is launched in.

IAM
---

Idenity and Access Management is used within cfncluster to provide an EC2 IAM Role for the instances. This role is a least privilged role specifically created for each cluster. cfncluster instances are given access only to the specific API calls that are required to deploy and manage the cluster. 

SNS
---

Simple Notification Service is used to receive notifications from Autoscaling. These events are called life cycle events, and are generated when an instance lauches or terminates in an Autoscaling Grpoup. Within cfncluster, the SNS topic for the Autoscaling Group is subnscibred to an SQS queue.

SQS
---

Simple Queuing Service is used to hold notifications(messages) from Autoscaling, sent through SNS. This decouples the 

EC2
---

Autscaling
----------

EBS
---

Cloudwatch
----------

S3
--

DynamoDB
--------

