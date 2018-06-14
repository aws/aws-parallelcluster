.. _custom_cookbook:

#######################################
Setting Up a Custom CfnCluster Cookbook
#######################################

.. warning::
    The following are instructions for use a custom version of the CfnCluster cookbook recipes.
    This is an advanced method of customizing CfnCluster, with many hard to debug pitfalls.
    The CfnCluster team highly recommends using :doc:`pre_post_install` scripts for customization, as post install hooks are generally easier to debug and more portable across releases of CfnCluster.

Steps
=====

#.  Identify the CfnCluster Cookbook working directory where you have cloned the CfnCluster Cookbook code ::

        _cookbookDir=<path to cookbook>

#.  Detect the current version of the CfnCluster Cookbook ::

        _version=$(grep version ${_cookbookDir}/metadata.rb|awk '{print $2}'| tr -d \')

#.  Create an archive of the CfnCluster Cookbook and calculate its md5 ::

        cd "${_cookbookDir}"
        _stashName=$(git stash create)
        git archive --format tar --prefix="cfncluster-cookbook-${_version}/" "${_stashName:-HEAD}" | gzip > "cfncluster-cookbook-${_version}.tgz"
        md5sum "cfncluster-cookbook-${_version}.tgz" > "cfncluster-cookbook-${_version}.md5"

#.  Create an S3 bucket and upload the archive, its md5 and its last modified date into the bucket, giving public readable permission through a public-read acl ::

        _bucket=<the bucket name>
        aws s3 cp --acl public-read cfncluster-cookbook-${_version}.tgz s3://${_bucket}/cookbooks/cfncluster-cookbook-${_version}.tgz
        aws s3 cp --acl public-read cfncluster-cookbook-${_version}.md5 s3://${_bucket}/cookbooks/cfncluster-cookbook-${_version}.md5
        aws s3api head-object --bucket ${_bucket} --key cookbooks/cfncluster-cookbook-${_version}.tgz --output text --query LastModified > cfncluster-cookbook-${_version}.tgz.date
        aws s3 cp --acl public-read cfncluster-cookbook-${_version}.tgz.date s3://${_bucket}/cookbooks/cfncluster-cookbook-${_version}.tgz.date


#.  Add the following variable to the cfncluster config file, under the `[cluster ...]` section" ::

        custom_chef_cookbook = https://s3.<the bucket region>.amazonaws.com/${_bucket}/cookbooks/cfncluster-cookbook-${_version}.tgz

