.. _aws_services:

AWS Services used in CfnCluster
===============================

The following Amazon Web Services (AWS) services are used in CfnCluster. 

* AWS CloudFormation
* AWS Identity and Access Management (IAM)
* Amazon SNS
* Amazon SQS
* Amazon EC2
* Auto Scaling
* Amazon EBS
* Amazon Cloud Watch
* Amazon S3
* Amazon DynamoDB

AWS CloudFormation
------------------

AWS CloudFormation is the core service used by CfnCluster. Each cluster is representated as a stack. All resources required by the cluster are defined within the CfnCluster CloudFormation template. CfnCluster cli commands typically map to CloudFormation stack commands, such as create, update and delete. Instances launched within a cluster make HTTPS calls to the CloudFormation Endpoint for the region the cluster is launched in.

For more details about AWS CloudFormation, see http://aws.amazon.com/cloudformation/

AWS Identity and Access Management (IAM)
----------------------------------------

IAM is used within CfnCluster to provide an Amazon EC2 IAM Role for the instances. This role is a least privilged role specifically created for each cluster. CfnCluster instances are given access only to the specific API calls that are required to deploy and manage the cluster. 

For more details about AWS Identity and Access Management, see http://aws.amazon.com/iam/

Amazon SNS
----------

Amazon Simple Notification Service is used to receive notifications from Auto Scaling. These events are called life cycle events, and are generated when an instance lauches or terminates in an Autoscaling Group. Within CfnCluster, the Amazon SNS topic for the Autoscaling Group is subscribed to an Amazon SQS queue.

For more details about Amazon SNS, see http://aws.amazon.com/sns/

Amazon SQS
----------

Amazon Simple Queuing Service is used to hold notifications(messages) from Auto Scaling, sent through Amazon SNS and notifications from the ComputeFleet instanes. This decouples the sending of notifications from the receiving and allows the Master to handle them through polling. The MasterServer runs Amazon SQSwatcher and polls the queue. AutoScaling and the ComputeFleet instanes post messages to the queue.

For more details about Amazon SQS, see http://aws.amazon.com/sqs/

Amazon EC2
----------

Amazon EC2 provides the compute for CfnCluster. The MasterServer and ComputeFleet are EC2 instances. Any instance type that support HVM can be selected. The MasterServer and ComputeFleet can be different instance types and the ComputeFleet can also be launched as Spot instances. Instance store volumes found on the instances are mounted as a striped LVM volume.

For more details about Amazon EC2, see http://aws.amazon.com/ec2/

Auto Scaling
------------

Auto Scaling is used to manage the ComputeFleet instances. These instances are managed as an AutoScaling Group and can either be elastically driven by workload or static and driven by the config. 

For more details about Auto Scaling, see http://aws.amazon.com/autoscaling/

Amazon EBS
----------

Amazon EBS provides the persistent storage for the shared volume. Any EBS settings can be passed through the config. EBS volumes can either be initialized empty or from an exisiting EBS snapshot.

For more details about Amazon EBS, see http://aws.amazon.com/ebs/

Amazon CloudWatch
------------------

Amazon CloudWatch provides metric collection and alarms for CfnCluster. The MasterServer publishes pending tasks (jobs) for each cluster. Two alarms are defined that based on parameters defined in the config will automatically increase the size of the ComputeFleet Auto Scaling group.

For more details, see http://aws.amazon.com/cloudwatch/

Amazon S3
---------

Amazon S3 is used to store the CfnCluster templates. Each region has a bucket with all templates. CfnCluster can be configured to allow allow CLI/SDK tools to use S3.

For more details, see http://aws.amazon.com/s3/

Amazon DynamoDB
---------------

Amazon DynamoDB is used to store minimal state of the cluster. The MasterServer tracks provisioned instances in a DynamoDB table.

For more details, see http://aws.amazon.com/dynamodb/
