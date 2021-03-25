#!/usr/bin/env bash
set -e

if ! command -v redoc-cli &> /dev/null
then
    echo "Please install redoc-cli: npm install -g redoc-cli"
    exit
fi
cd openapi
redoc-cli bundle ParallelCluster.openapi.json -o ParallelCluster.openapi.redoc.html
echo "Generated redoc bundle: spec/openapi/ParallelCluster.openapi.redoc.html"
