#!/usr/bin/env bash
set -ex

if ! command -v yq &> /dev/null
then
    echo "Please install yq: https://mikefarah.gitbook.io/yq/"
    echo "   GO111MODULE=on go get github.com/mikefarah/yq/v4; export PATH=\$PATH:~/go/bin"
    exit 1
fi
pushd smithy && ../../gradlew build && popd
yq eval -P smithy/build/smithyprojections/smithy/source/openapi/ParallelCluster.openapi.json > openapi/ParallelCluster.openapi.yaml
