.. _iam:

IAM in CfnCluster
========================

.. warning::
    Between CfnCluster 1.5.3 and 1.6.0 we added a change to the `CfnClusterInstancePolicy` that adds “s3:GetObject” permissions on objects in <REGION>-cfncluster bucket and cloudformation:DescribeStacks" permissions on <REGION>:<ACCOUNT_NAME>:<STACK_NAME>
    If you're using a custom policy (e.g. you specify "ec2_iam_role" in your config) be sure it includes this new permission.

    Between CfnCluster 1.4.2 and 1.5.0 we added a change to the `CfnClusterInstancePolicy` that adds "ec2:DescribeVolumes" permissions. If you're using a custom policy (e.g. you specify "ec2_iam_role" in your config) be sure it includes this new permission.

CfnCluster utilizes multiple AWS services to deploy and operate a cluster. The services used are listed in the :ref:`AWS Services used in CfnCluster <aws_services>` section of the documentation.

CfnCluster uses EC2 IAM roles to enable instances access to AWS services for the deployment and operation of the cluster. By default the EC2 IAM role is created as part of the cluster creation by CloudFormation. This means that the user creating the cluster must have the appropriate level of permissions

Defaults
--------

When using defaults, during cluster launch an EC2 IAM Role is created by the cluster, as well as all the resources required to launch the cluster. The user calling the create call must have the right level of permissions to create all the resources including an EC2 IAM Role. This level of permissions is typically an IAM user with the `AdministratorAccess` managed policy. More details on managed policies can be found here: http://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_managed-vs-inline.html#aws-managed-policies

Using an existing EC2 IAM role
------------------------------

When using CfnCluster with an existing EC2 IAM role, you must first define the IAM policy and role before attempting to launch the cluster. Typically the reason for using an exisiting EC2 IAM role within CfnCluster is to reduce the permissions granted to users launching clusters. Below is an example IAM policy for both the EC2 iam role and the CfnCluster IAM user. You should create both as individual policies in IAM and then attach to the appropriate resources. In both policies, you should replace REGION and AWS ACCOUNT ID with the appropriate values.

CfnClusterInstancePolicy
------------------------

::

  {
      "Version": "2012-10-17",
      "Statement": [
          {
              "Resource": [
                  "*"
              ],
              "Action": [
                  "ec2:DescribeVolumes",
                  "ec2:AttachVolume",
                  "ec2:DescribeInstanceAttribute",
                  "ec2:DescribeInstanceStatus",
                  "ec2:DescribeInstances"
              ],
              "Sid": "EC2",
              "Effect": "Allow"
          },
          {
              "Resource": [
                  "*"
              ],
              "Action": [
                  "dynamodb:ListTables"
              ],
              "Sid": "DynamoDBList",
              "Effect": "Allow"
          },
          {
              "Resource": [
                  "arn:aws:sqs:<REGION>:<AWS ACCOUNT ID>:cfncluster-*"
              ],
              "Action": [
                  "sqs:SendMessage",
                  "sqs:ReceiveMessage",
                  "sqs:ChangeMessageVisibility",
                  "sqs:DeleteMessage",
                  "sqs:GetQueueUrl"
              ],
              "Sid": "SQSQueue",
              "Effect": "Allow"
          },
          {
              "Resource": [
                  "*"
              ],
              "Action": [
                  "autoscaling:DescribeAutoScalingGroups",
                  "autoscaling:TerminateInstanceInAutoScalingGroup",
                  "autoscaling:SetDesiredCapacity",
                  "autoscaling:DescribeTags",
                  "autoScaling:UpdateAutoScalingGroup"
              ],
              "Sid": "Autoscaling",
              "Effect": "Allow"
          },
          {
              "Resource": [
                  "arn:aws:dynamodb:<REGION>:<AWS ACCOUNT ID>:table/cfncluster-*"
              ],
              "Action": [
                  "dynamodb:PutItem",
                  "dynamodb:Query",
                  "dynamodb:GetItem",
                  "dynamodb:DeleteItem",
                  "dynamodb:DescribeTable"
              ],
              "Sid": "DynamoDBTable",
              "Effect": "Allow"
          },
          {
              "Resource": [
                  "arn:aws:s3:::<REGION>-cfncluster/*"
              ],
              "Action": [
                  "s3:GetObject"
              ],
              "Sid": "S3GetObj",
              "Effect": "Allow"
          },
          {
              "Resource": [
                  "*"
              ],
              "Action": [
                  "sqs:ListQueues"
              ],
              "Sid": "SQSList",
              "Effect": "Allow"
          },
          {
              "Resource": [
                  "arn:aws:logs:*:*:*"
              ],
              "Action": [
                  "logs:*"
              ],
              "Sid": "CloudWatchLogs",
              "Effect": "Allow"
          }
      ]
  }

CfnClusterUserPolicy
--------------------

::

  {
      "Version": "2012-10-17",
      "Statement": [
          {
              "Sid": "EC2Describe",
              "Action": [
                  "ec2:DescribeKeyPairs",
                  "ec2:DescribeVpcs",
                  "ec2:DescribeSubnets",
                  "ec2:DescribeSecurityGroups",
                  "ec2:DescribePlacementGroups",
                  "ec2:DescribeImages",
                  "ec2:DescribeInstances",
                  "ec2:DescribeInstanceStatus",
                  "ec2:DescribeSnapshots",
                  "ec2:DescribeVolumes",
                  "ec2:DescribeVpcAttribute",
                  "ec2:DescribeAddresses",
                  "ec2:CreateTags",
                  "ec2:DescribeNetworkInterfaces",
                  "ec2:DescribeAvailabilityZones"
              ],
              "Effect": "Allow",
              "Resource": "*"
          },
          {
              "Sid": "EC2Modify",
              "Action": [
                  "ec2:CreateVolume",
                  "ec2:RunInstances",
                  "ec2:AllocateAddress",
                  "ec2:AssociateAddress",
                  "ec2:AttachNetworkInterface",
                  "ec2:AuthorizeSecurityGroupEgress",
                  "ec2:AuthorizeSecurityGroupIngress",
                  "ec2:CreateNetworkInterface",
                  "ec2:CreateSecurityGroup",
                  "ec2:ModifyVolumeAttribute",
                  "ec2:ModifyNetworkInterfaceAttribute",
                  "ec2:DeleteNetworkInterface",
                  "ec2:DeleteVolume",
                  "ec2:TerminateInstances",
                  "ec2:DeleteSecurityGroup",
                  "ec2:DisassociateAddress",
                  "ec2:RevokeSecurityGroupIngress",
                  "ec2:ReleaseAddress",
                  "ec2:CreatePlacementGroup",
                  "ec2:DeletePlacementGroup"
              ],
              "Effect": "Allow",
              "Resource": "*"
          },
          {
              "Sid": "AutoScalingDescribe",
              "Action": [
                  "autoscaling:DescribeAutoScalingGroups",
                  "autoscaling:DescribeLaunchConfigurations",
                  "autoscaling:DescribeAutoScalingInstances"
              ],
              "Effect": "Allow",
              "Resource": "*"
          },
          {
              "Sid": "AutoScalingModify",
              "Action": [
                  "autoscaling:CreateAutoScalingGroup",
                  "autoscaling:CreateLaunchConfiguration",
                  "autoscaling:PutNotificationConfiguration",
                  "autoscaling:UpdateAutoScalingGroup",
                  "autoscaling:PutScalingPolicy",
                  "autoscaling:DeleteLaunchConfiguration",
                  "autoscaling:DescribeScalingActivities",
                  "autoscaling:DeleteAutoScalingGroup",
                  "autoscaling:DeletePolicy"
              ],
              "Effect": "Allow",
              "Resource": "*"
          },
          {
              "Sid": "DynamoDBDescribe",
              "Action": [
                  "dynamodb:DescribeTable"
              ],
              "Effect": "Allow",
              "Resource": "*"
          },
          {
              "Sid": "DynamoDBModify",
              "Action": [
                "dynamodb:CreateTable",
                "dynamodb:DeleteTable"
              ],
              "Effect": "Allow",
              "Resource": "*"
          },
          {
              "Sid": "SQSDescribe",
              "Action": [
                  "sqs:GetQueueAttributes"
              ],
              "Effect": "Allow",
              "Resource": "*"
          },
          {
              "Sid": "SQSModify",
              "Action": [
                  "sqs:CreateQueue",
                  "sqs:SetQueueAttributes",
                  "sqs:DeleteQueue"
              ],
              "Effect": "Allow",
              "Resource": "*"
          },
          {
              "Sid": "SNSDescribe",
              "Action": [
                "sns:ListTopics",
                "sns:GetTopicAttributes"
              ],
              "Effect": "Allow",
              "Resource": "*"
          },
          {
              "Sid": "SNSModify",
              "Action": [
                  "sns:CreateTopic",
                  "sns:Subscribe",
                  "sns:DeleteTopic"
              ],
              "Effect": "Allow",
              "Resource": "*"
          },
          {
              "Sid": "CloudFormationDescribe",
              "Action": [
                  "cloudformation:DescribeStackEvents",
                  "cloudformation:DescribeStackResource",
                  "cloudformation:DescribeStackResources",
                  "cloudformation:DescribeStacks",
                  "cloudformation:ListStacks",
                  "cloudformation:GetTemplate"
              ],
              "Effect": "Allow",
              "Resource": "*"
          },
          {
              "Sid": "CloudFormationModify",
              "Action": [
                  "cloudformation:CreateStack",
                  "cloudformation:DeleteStack",
                  "cloudformation:UpdateStack"
              ],
              "Effect": "Allow",
              "Resource": "*"
          },
          {
              "Sid": "S3CfnClusterReadOnly",
              "Action": [
                  "s3:Get*",
                  "s3:List*"
              ],
              "Effect": "Allow",
              "Resource": [
                  "arn:aws:s3:::<REGION>-cfncluster*"
              ]
          },
          {
              "Sid": "IAMModify",
              "Action": [
                  "iam:PassRole",
                  "iam:CreateRole",
                  "iam:DeleteRole",
                  "iam:GetRole",
                  "iam:SimulatePrincipalPolicy"
              ],
              "Effect": "Allow",
              "Resource": "arn:aws:iam::<AWS ACCOUNT ID>:role/<CFNCLUSTER EC2 ROLE NAME>"
          },
          {
              "Sid": "IAMCreateInstanceProfile",
              "Action": [
                  "iam:CreateInstanceProfile",
                  "iam:DeleteInstanceProfile"
              ],
              "Effect": "Allow",
              "Resource": "arn:aws:iam::<AWS ACCOUNT ID>:instance-profile/*"
          },
          {
              "Sid": "IAMInstanceProfile",
              "Action": [
                  "iam:AddRoleToInstanceProfile",
                  "iam:RemoveRoleFromInstanceProfile",
                  "iam:PutRolePolicy",
                  "iam:DeleteRolePolicy"
              ],
              "Effect": "Allow",
              "Resource": "*"
          }
      ]
  }
