#!/usr/bin/env bash
set -ex

pushd smithy && gradle build && popd
cp smithy/build/smithyprojections/smithy/source/openapi/ParallelCluster.openapi.json openapi/
