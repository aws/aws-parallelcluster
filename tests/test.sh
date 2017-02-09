#!/bin/bash
# Very basic first tests

set -x
echo $PATH
which cfncluster

# display version number
cfncluster version

# display help message
cfncluster --help
