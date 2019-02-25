#!/bin/bash
# Very basic first tests

set -ex
echo $PATH
which pcluster
pip check
pcluster version
pcluster --help
