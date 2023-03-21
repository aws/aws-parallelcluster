#!/usr/bin/env bash
set -ex

if ! command -v yq &> /dev/null
then
    echo "Please install yq: https://mikefarah.gitbook.io/yq/"
    echo "   GO111MODULE=on go get github.com/mikefarah/yq/v4; export PATH=\$PATH:~/go/bin"
    exit 1
fi
pushd smithy && ../../gradlew build && popd
GENERATED_JSON_PATH="smithy/build/smithyprojections/smithy/source/openapi/ParallelCluster.openapi.json"
./spec_overrides.sh "$GENERATED_JSON_PATH"
# Convert json into yaml
yq eval -P $GENERATED_JSON_PATH -o yaml > openapi/ParallelCluster.openapi.yaml
