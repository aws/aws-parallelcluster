.. _iam:

IAM in AWS ParallelCluster
==========================

AWS ParallelCluster utilizes multiple AWS services to deploy and operate a cluster. The services used are listed in the
:ref:`AWS Services used in AWS ParallelCluster <aws_services>` section of the documentation.

AWS ParallelCluster uses EC2 IAM roles to enable instances access to AWS services for the deployment and operation of
the cluster. By default the EC2 IAM role is created as part of the cluster creation by CloudFormation. This means that
the user creating the cluster must have the appropriate level of permissions

Defaults
--------

When using defaults, during cluster launch an EC2 IAM Role is created by the cluster, as well as all the resources
required to launch the cluster. The user calling the create call must have the right level of permissions to create all
the resources including an EC2 IAM Role. This level of permissions is typically an IAM user with the
`AdministratorAccess` managed policy. More details on managed policies can be found here:
http://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_managed-vs-inline.html#aws-managed-policies

Using an existing EC2 IAM role
------------------------------

When using AWS ParallelCluster with an existing EC2 IAM role, you must first define the IAM policy and role before
attempting to launch the cluster. Typically the reason for using an existing EC2 IAM role within AWS ParallelCluster is
to reduce the permissions granted to users launching clusters. Below is an example IAM policy for both the EC2 IAM role
and the AWS ParallelCluster IAM user. You should create both as individual policies in IAM and then attach to the
appropriate resources. In both policies, you should replace REGION and AWS ACCOUNT ID with the appropriate values.

ParallelClusterInstancePolicy
-----------------------------

In case you are using SGE, Slurm or Torque as a scheduler:

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
                  "ec2:DescribeInstances",
                  "ec2:DescribeRegions"
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
                  "arn:aws:sqs:<REGION>:<AWS ACCOUNT ID>:parallelcluster-*"
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
                  "autoScaling:UpdateAutoScalingGroup",
                  "autoscaling:SetInstanceHealth"
              ],
              "Sid": "Autoscaling",
              "Effect": "Allow"
          },
          {
              "Resource": [
                  "arn:aws:dynamodb:<REGION>:<AWS ACCOUNT ID>:table/parallelcluster-*"
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
                  "arn:aws:s3:::<REGION>-aws-parallelcluster/*"
              ],
              "Action": [
                  "s3:GetObject"
              ],
              "Sid": "S3GetObj",
              "Effect": "Allow"
          },
          {
              "Resource": [
                  "arn:aws:cloudformation:<REGION>:<AWS ACCOUNT ID>:stack/parallelcluster-*/*"
              ],
              "Action": [
                  "cloudformation:DescribeStacks",
                  "cloudformation:DescribeStackResource"
              ],
              "Sid": "CloudFormationDescribe",
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
          }
      ]
  }

In case you are using awsbatch as a scheduler, you need to include the same policies
as the ones assigned to the BatchUserRole that is defined in the Batch CloudFormation nested stack.
The BatchUserRole ARN is provided as a stack output.
Here is an overview of the required permissions:

::

  {
      "Version": "2012-10-17",
      "Statement": [
          {
              "Action": [
                  "batch:SubmitJob",
                  "batch:RegisterJobDefinition",
                  "cloudformation:DescribeStacks",
                  "ecs:ListContainerInstances",
                  "ecs:DescribeContainerInstances",
                  "logs:GetLogEvents",
                  "logs:FilterLogEvents",
                  "s3:PutObject",
                  "s3:Get*",
                  "s3:DeleteObject",
                  "iam:PassRole"
              ],
              "Resource": [
                  "arn:aws:batch:<REGION>:<AWS ACCOUNT ID>:job-definition/<AWS_BATCH_STACK - JOB_DEFINITION_SERIAL_NAME>:1",
                  "arn:aws:batch:<REGION>:<AWS ACCOUNT ID>:job-definition/<AWS_BATCH_STACK - JOB_DEFINITION_MNP_NAME>*",
                  "arn:aws:batch:<REGION>:<AWS ACCOUNT ID>:job-queue/<AWS_BATCH_STACK - JOB_QUEUE_NAME>",
                  "arn:aws:cloudformation:<REGION>:<AWS ACCOUNT ID>:stack/<STACK NAME>/*",
                  "arn:aws:s3:::<RESOURCES S3 BUCKET>/batch/*",
                  "arn:aws:iam::<AWS ACCOUNT ID>:role/<AWS_BATCH_STACK - JOB_ROLE>",
                  "arn:aws:ecs:<REGION>:<AWS ACCOUNT ID>:cluster/<ECS COMPUTE ENVIRONMENT>",
                  "arn:aws:ecs:<REGION>:<AWS ACCOUNT ID>:container-instance/*",
                  "arn:aws:logs:<REGION>:<AWS ACCOUNT ID>:log-group:/aws/batch/job:log-stream:*"
              ],
              "Effect": "Allow"
          },
          {
              "Action": [
                  "s3:List*"
              ],
              "Resource": [
                  "arn:aws:s3:::<RESOURCES S3 BUCKET>"
              ],
              "Effect": "Allow"
          },
          {
              "Action": [
                  "batch:DescribeJobQueues",
                  "batch:TerminateJob",
                  "batch:DescribeJobs",
                  "batch:CancelJob",
                  "batch:DescribeJobDefinitions",
                  "batch:ListJobs",
                  "batch:DescribeComputeEnvironments",
                  "ec2:DescribeInstances"
              ],
              "Resource": "*",
              "Effect": "Allow"
          }
      ]
  }


ParallelClusterUserPolicy
-------------------------

In case you are using SGE, Slurm or Torque as a scheduler:

Note, if you use a custom role, ``ec2_iam_role = role_name``, you'll need to change the IAM resource to include
the name of that role.

From: ::

  "Resource": "arn:aws:iam::<AWS ACCOUNT ID>:role/parallelcluster-*"

To: ::

  "Resource": "arn:aws:iam::<AWS ACCOUNT ID>:role/<role_name>"

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
                  "autoscaling:DescribeAutoScalingInstances"
              ],
              "Effect": "Allow",
              "Resource": "*"
          },
          {
              "Sid": "AutoScalingModify",
              "Action": [
                  "autoscaling:CreateAutoScalingGroup",
                  "ec2:CreateLaunchTemplate",
                  "ec2:ModifyLaunchTemplate",
                  "ec2:DeleteLaunchTemplate",
                  "ec2:DescribeLaunchTemplates",
                  "ec2:DescribeLaunchTemplateVersions",
                  "autoscaling:PutNotificationConfiguration",
                  "autoscaling:UpdateAutoScalingGroup",
                  "autoscaling:PutScalingPolicy",
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
              "Sid": "S3ParallelClusterReadOnly",
              "Action": [
                  "s3:Get*",
                  "s3:List*"
              ],
              "Effect": "Allow",
              "Resource": [
                  "arn:aws:s3:::<REGION>-aws-parallelcluster*"
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
              "Resource": "arn:aws:iam::<AWS ACCOUNT ID>:role/parallelcluster-*"
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
          },
          {
              "Sid": "EFSDescribe",
              "Action": [
                  "efs:DescribeMountTargets",
                  "efs:DescribeMountTargetSecurityGroups"
              ],
              "Effect": "Allow",
              "Resource": "*"
          },
          {
              "Sid": "SSMDescribe",
              "Action": [
                  "ssm:GetParametersByPath"
              ],
              "Effect": "Allow",
              "Resource": "*"
          }
      ]
  }

In case you are using awsbatch as a scheduler:

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
        "Sid": "DynamoDB",
        "Action": [
          "dynamodb:DescribeTable",
          "dynamodb:CreateTable",
          "dynamodb:DeleteTable"
        ],
        "Effect": "Allow",
        "Resource": "arn:aws:dynamodb:<REGION>:<AWS ACCOUNT ID>:table/parallelcluster-*"
      },
      {
        "Sid": "CloudFormation",
        "Action": [
          "cloudformation:DescribeStackEvents",
          "cloudformation:DescribeStackResource",
          "cloudformation:DescribeStackResources",
          "cloudformation:DescribeStacks",
          "cloudformation:ListStacks",
          "cloudformation:GetTemplate",
          "cloudformation:CreateStack",
          "cloudformation:DeleteStack",
          "cloudformation:UpdateStack"
        ],
        "Effect": "Allow",
        "Resource": "arn:aws:cloudformation:<REGION>:<AWS ACCOUNT ID>:stack/parallelcluster-*"
      },
      {
        "Sid": "SQS",
        "Action": [
          "sqs:GetQueueAttributes",
          "sqs:CreateQueue",
          "sqs:SetQueueAttributes",
          "sqs:DeleteQueue"
        ],
        "Effect": "Allow",
        "Resource": "*"
      },
      {
        "Sid": "SQSQueue",
        "Action": [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:ChangeMessageVisibility",
          "sqs:DeleteMessage",
          "sqs:GetQueueUrl"
        ],
        "Effect": "Allow",
        "Resource": "arn:aws:sqs:<REGION>:<AWS ACCOUNT ID>:parallelcluster-*"
      },
      {
        "Sid": "SNS",
        "Action": [
          "sns:ListTopics",
          "sns:GetTopicAttributes",
          "sns:CreateTopic",
          "sns:Subscribe",
          "sns:DeleteTopic"],
        "Effect": "Allow",
        "Resource": "*"
      },
      {
        "Sid": "IAMRole",
        "Action": [
          "iam:PassRole",
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:GetRole",
          "iam:SimulatePrincipalPolicy"
        ],
        "Effect": "Allow",
        "Resource": "arn:aws:iam::<AWS ACCOUNT ID>:role/parallelcluster-*"
      },
      {
        "Sid": "IAMInstanceProfile",
        "Action": [
          "iam:CreateInstanceProfile",
          "iam:DeleteInstanceProfile",
          "iam:GetInstanceProfile",
          "iam:PassRole"
        ],
        "Effect": "Allow",
        "Resource": "arn:aws:iam::<AWS ACCOUNT ID>:instance-profile/*"
      },
      {
        "Sid": "IAM",
        "Action": [
          "iam:AddRoleToInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:PutRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:AttachRolePolicy",
          "iam:DetachRolePolicy"
        ],
        "Effect": "Allow",
        "Resource": "*"
      },
      {
        "Sid": "S3ResourcesBucket",
        "Action": ["s3:*"],
        "Effect": "Allow",
        "Resource": ["arn:aws:s3:::parallelcluster-*"]
      },
      {
        "Sid": "S3ParallelClusterReadOnly",
        "Action": [
          "s3:Get*",
          "s3:List*"
        ],
        "Effect": "Allow",
        "Resource": ["arn:aws:s3:::<REGION>-aws-parallelcluster/*"]
      },
      {
        "Sid": "Lambda",
        "Action": [
          "lambda:CreateFunction",
          "lambda:DeleteFunction",
          "lambda:GetFunctionConfiguration",
          "lambda:InvokeFunction",
          "lambda:AddPermission",
          "lambda:RemovePermission"
        ],
        "Effect": "Allow",
        "Resource": "arn:aws:lambda:<REGION>:<AWS ACCOUNT ID>:function:parallelcluster-*"
      },
      {
        "Sid": "Logs",
        "Effect": "Allow",
        "Action": ["logs:*"],
        "Resource": "arn:aws:logs:<REGION>:<AWS ACCOUNT ID>:*"
      },
      {
        "Sid": "CodeBuild",
        "Effect": "Allow",
        "Action": ["codebuild:*"],
        "Resource": "arn:aws:codebuild:<REGION>:<AWS ACCOUNT ID>:project/parallelcluster-*"
      },
      {
        "Sid": "ECR",
        "Effect": "Allow",
        "Action": ["ecr:*"],
        "Resource": "*"
      },
      {
        "Sid": "Batch",
        "Effect": "Allow",
        "Action": ["batch:*"],
        "Resource": "*"
      },
      {
        "Sid": "AmazonCloudWatchEvents",
        "Effect": "Allow",
        "Action": ["events:*"],
        "Resource": "*"
      }
    ]
  }

