#!/usr/bin/env bash
set -ex

if ! command -v yq &> /dev/null
then
    echo "Please install yq: https://mikefarah.gitbook.io/yq/"
    exit 1
fi
pushd smithy && gradle build && popd
yq eval -P smithy/build/smithyprojections/smithy/source/openapi/ParallelCluster.openapi.json > openapi/ParallelCluster.openapi.yaml
