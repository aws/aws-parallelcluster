#!/bin/bash
# This script installs the necessary software stack for StarCCM+.
# Note: The same cluster is shared by both test_openfoam and test_starccm.
# The cluster will be created by whichever test (test_openfoam or test_starccm) is executed first.
# If test_openfoam is executed first, it will also need to install the required dependencies.
set -ex

sudo yum install -y libnsl
