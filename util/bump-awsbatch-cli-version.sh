#!/bin/bash

set -ex

if [ -z "$1" ]; then
    echo "New version not specified. Usage: bump-awsbatch-cli-version.sh NEW_VERSION"
    exit 1
fi

NEW_VERSION=$1
CURRENT_VERSION=$(sed -ne "s/^VERSION = \"\(.*\)\"/\1/p" awsbatch-cli/setup.py)
sed -i "s/VERSION = \"$CURRENT_VERSION\"/VERSION = \"$NEW_VERSION\"/g" awsbatch-cli/setup.py
