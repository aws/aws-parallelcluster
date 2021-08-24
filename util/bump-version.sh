#!/bin/bash

set -ex

if [ -z "$1" ]; then
    echo "New version not specified. Usage: bump-version.sh NEW_VERSION"
    exit 1
fi

NEW_VERSION=$1
NEW_VERSION_SHORT=$(echo ${NEW_VERSION} | grep -Eo "[0-9]+\.[0-9]+\.[0-9]+")
CURRENT_VERSION=$(sed -ne "s/^VERSION = \"\(.*\)\"/\1/p" cli/setup.py)
CURRENT_VERSION_SHORT=$(echo ${CURRENT_VERSION} | grep -Eo "[0-9]+\.[0-9]+\.[0-9]+")
sed -i "s/VERSION = \"$CURRENT_VERSION\"/VERSION = \"$NEW_VERSION\"/g" cli/setup.py

sed -i "s/\"parallelcluster\": \"$CURRENT_VERSION\"/\"parallelcluster\": \"$NEW_VERSION\"/g" cli/src/pcluster/constants.py
sed -i "s/aws-parallelcluster-cookbook-$CURRENT_VERSION/aws-parallelcluster-cookbook-$NEW_VERSION/g" cli/src/pcluster/constants.py

sed -i "s|pcluster-api:$CURRENT_VERSION|pcluster-api:$NEW_VERSION|g" api/infrastructure/parallelcluster-api.yaml
sed -i "s|parallelcluster/$CURRENT_VERSION|parallelcluster/$NEW_VERSION|g" api/infrastructure/parallelcluster-api.yaml
sed -i "s| Version: $CURRENT_VERSION| Version: $NEW_VERSION|g" api/infrastructure/parallelcluster-api.yaml
sed -i "s| ShortVersion: $CURRENT_VERSION_SHORT| ShortVersion: $NEW_VERSION_SHORT|g" api/infrastructure/parallelcluster-api.yaml
