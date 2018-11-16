.. _custom_cookbook:

################################################
Setting Up a Custom AWS ParallelCluster Cookbook
################################################

.. warning::
    The following are instructions for use a custom version of the AWS ParallelCluster cookbook recipes.
    This is an advanced method of customizing AWS ParallelCluster, with many hard to debug pitfalls.
    The AWS ParallelCluster team highly recommends using :doc:`pre_post_install` scripts for customization,
    as post install hooks are generally easier to debug and more portable across releases of AWS ParallelCluster.

Steps
=====

#.  Identify the AWS ParallelCluster Cookbook working directory where you have cloned the AWS ParallelCluster Cookbook
    code ::

        _cookbookDir=<path to cookbook>

#.  Detect the current version of the AWS ParallelCluster Cookbook ::

        _version=$(grep version ${_cookbookDir}/metadata.rb|awk '{print $2}'| tr -d \')

#.  Create an archive of the AWS ParallelCluster Cookbook and calculate its md5 ::

        cd "${_cookbookDir}"
        _stashName=$(git stash create)
        git archive --format tar --prefix="aws-parallelcluster-cookbook-${_version}/" "${_stashName:-HEAD}" | gzip > "aws-parallelcluster-cookbook-${_version}.tgz"
        md5sum "aws-parallelcluster-cookbook-${_version}.tgz" > "aws-parallelcluster-cookbook-${_version}.md5"

#.  Create an S3 bucket and upload the archive, its md5 and its last modified date into the bucket, giving public
    readable permission through a public-read ACL ::

        _bucket=<the bucket name>
        aws s3 cp --acl public-read aws-parallelcluster-cookbook-${_version}.tgz s3://${_bucket}/cookbooks/aws-parallelcluster-cookbook-${_version}.tgz
        aws s3 cp --acl public-read aws-parallelcluster-cookbook-${_version}.md5 s3://${_bucket}/cookbooks/aws-parallelcluster-cookbook-${_version}.md5
        aws s3api head-object --bucket ${_bucket} --key cookbooks/aws-parallelcluster-cookbook-${_version}.tgz --output text --query LastModified > aws-parallelcluster-cookbook-${_version}.tgz.date
        aws s3 cp --acl public-read aws-parallelcluster-cookbook-${_version}.tgz.date s3://${_bucket}/cookbooks/aws-parallelcluster-cookbook-${_version}.tgz.date


#.  Add the following variable to the AWS ParallelCluster config file, under the `[cluster ...]` section" ::

        custom_chef_cookbook = https://s3.<the bucket region>.amazonaws.com/${_bucket}/cookbooks/aws-parallelcluster-cookbook-${_version}.tgz


.. spelling::
    md
