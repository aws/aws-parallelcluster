.. _custom_node_package:

####################################################
Setting Up a Custom AWS ParallelCluster Node Package
####################################################

.. warning::
    The following are instructions for use a custom version of the AWS ParallelCluster Node package.
    This is an advanced method of customizing AWS ParallelCluster, with many hard to debug pitfalls.
    The AWS ParallelCluster team highly recommends using :doc:`pre_post_install` scripts for customization, as post
    install hooks are generally easier to debug and more portable across releases of AWS ParallelCluster.

Steps
=====

#.  Identify the AWS ParallelCluster Node working directory where you have cloned the AWS ParallelCluster Node code ::

        _nodeDir=<path to node package>

#.  Detect the current version of the AWS ParallelCluster Node ::

        _version=$(grep "version = \"" ${_nodeDir}/setup.py |awk '{print $3}' | tr -d \")

#.  Create an archive of the AWS ParallelCluster Node ::

        cd "${_nodeDir}"
        _stashName=$(git stash create)
        git archive --format tar --prefix="aws-parallelcluster-node-${_version}/" "${_stashName:-HEAD}" | gzip > "aws-parallelcluster-node-${_version}.tgz"

#.  Create an S3 bucket and upload the archive into the bucket, giving public readable permission through a public-read
    ACL ::

        _bucket=<the bucket name>
        aws s3 cp --acl public-read aws-parallelcluster-node-${_version}.tgz s3://${_bucket}/node/aws-parallelcluster-node-${_version}.tgz


#.  Add the following variable to the AWS ParallelCluster config file, under the `[cluster ...]` section" ::

        extra_json = { "cluster" : { "custom_node_package" : "https://s3.<the bucket region>.amazonaws.com/${_bucket}/node/aws-parallelcluster-node-${_version}.tgz" } }

