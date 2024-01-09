#!/usr/bin/env bash
set -ex

YAML_PATH=$1
INDEX="$(yq '.paths["/v3/clusters/{clusterName}/logstreams"].get.parameters.[] | select(.name == "filters") | path | .[-1]' "$YAML_PATH")"
export INDEX
yq e -i '.paths["/v3/clusters/{clusterName}/logstreams"].get.parameters[env(INDEX)].style = "spaceDelimited"' "$YAML_PATH"
