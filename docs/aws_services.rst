.. _aws_services:

AWS Services Used in AWS ParallelCluster
========================================

The following AWS services are used in AWS ParallelCluster:

* AWS CloudFormation
* AWS Identity and Access Management (IAM)
* Amazon SNS
* Amazon SQS
* Amazon EC2
* AWS Auto Scaling
* Amazon EBS
* Amazon S3
* Amazon DynamoDB
* AWS Batch
* AWS CodeBuild
* AWS Lambda
* Amazon Elastic Container Registry (ECR)
* Amazon CloudWatch

.. _aws_services_cloudformation:

AWS CloudFormation
------------------

AWS CloudFormation is the core service used by AWS ParallelCluster.  Each cluster is represented as a stack.
All resources required by the cluster are defined within the AWS ParallelCluster CloudFormation template.
AWS ParallelCluster CLI commands typically map to CloudFormation stack commands, such as create, update and delete.
Instances launched within a cluster make HTTPS calls to the CloudFormation endpoint for the region
in which the cluster is launched.

For more details about AWS CloudFormation, please visit: http://aws.amazon.com/cloudformation/

AWS Identity and Access Management (IAM)
----------------------------------------

AWS IAM is used within AWS ParallelCluster to provide a least privileged Amazon EC2 IAM Role for the instances
that is specific to each individual cluster.  AWS ParallelCluster instances are given access only to the
specific API calls that are required to deploy and manage the cluster.

With AWS Batch clusters, IAM Roles are also created for the components involved with the Docker image building process
at cluster creation time.
These components include the Lambda functions allowed to add and delete Docker images to and from the ECR repository,
and to delete the S3 bucket created for the cluster and its CodeBuild project.
There are also roles for the AWS Batch resources, instances, and jobs.

For more details about AWS Identity and Access Management, please visit: http://aws.amazon.com/iam/

Amazon Simple Notification Service (SNS)
----------------------------------------

Amazon SNS is used to receive notifications whenever an instance launches or terminates in an Autoscaling Group.
Within AWS ParallelCluster, the Amazon SNS topic for the Autoscaling Group is subscribed to an Amazon SQS queue.

The service is not used with AWS Batch clusters.

For more details about Amazon SNS, please visit: http://aws.amazon.com/sns/

Amazon Simple Queuing Service (SQS)
-----------------------------------

Amazon SQS is used to hold notifications (messages) from Auto Scaling events sent through Amazon SNS and notifications
from the ComputeFleet instances.  This decouples the sending of notifications from the receiving and allows the Master
to handle them through polling.  The MasterServer runs Amazon SQSwatcher and polls the queue. AutoScaling and the
ComputeFleet instances post messages to the queue.

The service is not used with AWS Batch clusters.

For more details about Amazon SQS, please visit: http://aws.amazon.com/sqs/

Amazon EC2
----------

Amazon EC2 provides the compute for AWS ParallelCluster.  The MasterServer and ComputeFleet are EC2 instances.
Any instance type that supports HVM can be selected. The MasterServer and ComputeFleet can be different instance types.
The ComputeFleet can also be launched using Spot instances.
Instance store volumes found on the instances are mounted as a striped LVM volume.

For more details about Amazon EC2, please visit: http://aws.amazon.com/ec2/

AWS Auto Scaling
----------------

AWS Auto Scaling is used to manage the ComputeFleet instances.  These instances are managed as an AutoScaling Group and
can either be elastically driven by workload or statically configured in the base cluster configuration.

The service is not used with AWS Batch clusters.

For more details about Auto Scaling, please visit: http://aws.amazon.com/autoscaling/

Amazon Elastic Block Store (EBS)
--------------------------------

Amazon EBS provides persistent storage for the shared volumes.  Any EBS settings can be passed through the config.
EBS volumes can either be initialized empty or from an existing EBS snapshot.
RAID configurations are also supported.

For more details about Amazon EBS, please visit: http://aws.amazon.com/ebs/

Amazon S3
---------

Amazon S3 is used to store the AWS ParallelCluster templates.  Each region has a bucket with all templates.
AWS ParallelCluster can be configured to allow the CLI/SDK tools to use S3.

With AWS Batch, an S3 bucket in the customer's account is created to store artifacts used by the Docker
image creation process and the jobs scripts generated jobs are submitted from the user's machine.

For more details, please visit: http://aws.amazon.com/s3/

Amazon DynamoDB
---------------

Amazon DynamoDB is used to maintain cluster state.  The MasterServer tracks provisioned instances in a DynamoDB table.

This service is not used with AWS Batch clusters.

For more details, please visit: http://aws.amazon.com/dynamodb/

AWS Batch
---------
AWS Batch is an AWS-managed job scheduler that dynamically provisions the optimal quantity and type of compute
resources (e.g., CPU or memory optimized instances) based on the volume and specific resource requirements of the batch
jobs submitted.  With AWS Batch, there is no need to install and manage batch computing software or server clusters that
are used to run jobs.

This service is only used with AWS Batch clusters.

For more details, please visit: https://aws.amazon.com/batch/

AWS CodeBuild
-------------
AWS CodeBuild is used to automatically and transparently build Docker images at cluster creation time.

This service is only used with AWS Batch clusters.

For more details, please visit: https://aws.amazon.com/codebuild/

AWS Lambda
----------
AWS Lambda runs functions that orchestrate the Docker image creation and custom cluster resource cleanup processes.

This service is only used with AWS Batch clusters.

For more details, please visit: https://aws.amazon.com/lambda/

Amazon Elastic Container Registry (ECR)
---------------------------------------

Amazon ECR stores the Docker images built at cluster creation time.  The Docker images are then used by AWS Batch to run
the containers for the submitted jobs.

The service is only used with AWS Batch clusters.

For more details, please visit: https://aws.amazon.com/ecr/

Amazon CloudWatch
-----------------
Amazon CloudWatch is used to log Docker image build steps and the standard output and error of AWS Batch jobs.

The service is only used with AWS Batch clusters.

For more details, please visit: https://aws.amazon.com/cloudwatch/

.. spelling::
   CloudWatch
