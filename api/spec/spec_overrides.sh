#!/usr/bin/env bash
set -ex

YAML_PATH=$1
export INDEX="$(yq '.paths["/v3/clusters/{clusterName}/logstreams"].get.parameters.[] | select(.name == "filters") | path | .[-1]' "$YAML_PATH")"
yq e -i '.paths["/v3/clusters/{clusterName}/logstreams"].get.parameters[env(INDEX)].style = "spaceDelimited"' "$YAML_PATH"
