.. _custom_node_package:

############################################
Setting Up a Custom CfnCluster Node Package
############################################

.. warning::
    Using a custom CfnCluster Node package is not the recommended approach for customizing CfnCluster.

Before reading any further, take a look at the :doc:`pre_post_install` section of the documentation to determine if the modifications you wish to make can be scripted and supported with future CfnCluster releases.

Steps
=====

#.  Identify the CfnCluster Node working directory where you have cloned the CfnCluster Node code ::

        _nodeDir=<path to node package>

#.  Detect the current version of the CfnCluster Node ::

        _version=$(grep "version = \"" ${_nodeDir}/setup.py |awk '{print $3}' | tr -d \")

#.  Create an archive of the CfnCluster Node ::

        cd "${_nodeDir}"
        _stashName=$(git stash create)
        git archive --format tar --prefix="cfncluster-node-${_version}/" "${_stashName:-HEAD}" | gzip > "cfncluster-node-${_version}.tgz"

#.  Create an S3 bucket and upload the archive into the bucket, giving public readable permission through a public-read acl ::

        _bucket=<the bucket name>
        aws s3 cp --acl public-read cfncluster-node-${_version}.tgz s3://${_bucket}/node/cfncluster-node-${_version}.tgz


#.  Add the following variable to the CfnCluster config file, under the `[cluster ...]` section" ::

        extra_json = { "cfncluster" : { "custom_node_package" : "https://s3.<the bucket region>.amazonaws.com/${_bucket}/node/cfncluster-node-${_version}.tgz" } }

