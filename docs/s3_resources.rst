.. _s3_resources:

Working with S3
===============

Accessing S3 within AWS ParallelCluster can be controlled through two parameters in the AWS ParallelCluster config.

::

  # Specify S3 resource which AWS ParallelCluster nodes will be granted read-only access
  # (defaults to NONE)
  s3_read_resource = NONE
  # Specify S3 resource which AWS ParallelCluster nodes will be granted read-write access
  # (defaults to NONE)
  s3_read_write_resource = NONE

Both parameters accept either ``*`` or a valid S3 ARN. For details of how to specify S3 ARNs, please see
http://docs.aws.amazon.com/general/latest/gr/aws-arns-and-namespaces.html#arn-syntax-s3

Examples
--------

The following example gives you read access to any object in the bucket `my_corporate_bucket`.

::

  s3_read_resource = arn:aws:s3:::my_corporate_bucket/*

This next example gives you read access to the bucket. This does **not** let you read items from the bucket.

::

  s3_read_resource = arn:aws:s3:::my_corporate_bucket

This last example gives you read access to the bucket and to the items stored in the bucket.

::

  s3_read_resource = arn:aws:s3:::my_corporate_bucket*
