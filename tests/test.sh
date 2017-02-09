#!/bin/bash
# Very basic first tests

set -x
echo $PATH
which cfncluster
cfncluster version
cfncluster --help
